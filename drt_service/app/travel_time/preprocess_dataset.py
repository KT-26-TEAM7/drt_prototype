"""한태희 담당: 원본 ETA 데이터를 모델 입력용 표준 테이블로 전처리한다."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.travel_time.estimate_duration import (
    StationIndex,
    hour_band,
    normalize_speed_level,
    normalize_station_name,
    normalize_weather,
    normalize_weekday,
    speed_level_from_kmh,
)

CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "origin_station": (
        "origin_station", "start_station", "departure_station", "from_station", "board_station",
        "출발정류장", "출발_정류장", "승차정류장", "승차_정류장",
    ),
    "destination_station": (
        "destination_station", "end_station", "arrival_station", "to_station", "alight_station",
        "도착정류장", "도착_정류장", "하차정류장", "하차_정류장",
    ),
    "travel_time_sec": (
        "travel_time_sec", "eta_sec", "duration_sec", "duration_s", "travel_seconds",
        "estimated_time_sec", "소요시간초", "이동시간초", "소요시간_sec", "travel_time",
    ),
    "weather": ("weather", "weather_type", "날씨", "기상"),
    "weekday": ("weekday", "day_of_week", "dow", "요일"),
    "speed_level": ("speed_level", "speed_class", "speed_category", "속도등급", "속도구간", "속도_상중하"),
    "datetime": ("datetime", "timestamp", "recorded_at", "created_at", "date_time", "일시", "측정일시"),
    "speed_kmh": ("speed_kmh", "speed", "avg_speed_kmh", "average_speed_kmh", "속도", "평균속도", "속도_kmh"),
    "hour": ("hour", "시간", "hour_of_day"),
    "hour_band": ("hour_band", "time_band", "시간대", "시간구간"),
    "route_distance_m": (
        "route_distance_m", "distance_m", "travel_distance_m", "route_m", "이동거리m", "거리_m",
    ),
}

REQUIRED_BASE = ("origin_station", "destination_station", "travel_time_sec", "weather")
OUTPUT_COLUMNS = (
    "origin_station", "destination_station", "weather", "weekday", "hour",
    "hour_band", "speed_level", "route_distance_m", "travel_time_sec",
)


def _column_key(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower())


def canonicalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """팀원별로 다른 컬럼명을 ETA 표준 컬럼명으로 정규화한다."""
    current = {_column_key(column): column for column in frame.columns}
    rename: dict[str, str] = {}
    for canonical, aliases in CANONICAL_ALIASES.items():
        if canonical in frame.columns:
            continue
        for alias in aliases:
            key = _column_key(alias)
            original = current.get(key)
            if original is not None:
                rename[original] = canonical
                break
    return frame.rename(columns=rename)


@dataclass(slots=True)
class PreprocessSummary:
    input_path: str
    output_path: str
    rows_read: int = 0
    rows_written: int = 0
    rows_dropped: int = 0
    chunks: int = 0
    derived_weekday: bool = False
    derived_hour: bool = False
    derived_speed_level: bool = False
    dropped_columns: tuple[str, ...] = ("datetime", "speed_kmh")
    output_columns: tuple[str, ...] = OUTPUT_COLUMNS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_normalize(series: pd.Series, fn, default: str | None = None) -> pd.Series:
    def convert(value: Any) -> str | None:
        if pd.isna(value) or str(value).strip() == "":
            return default
        try:
            return fn(value)
        except (ValueError, TypeError):
            return None

    return series.map(convert)


def _derive_route_distance(
    origin: pd.Series, destination: pd.Series, station_index: StationIndex | None,
) -> pd.Series:
    if station_index is None:
        return pd.Series(np.nan, index=origin.index, dtype=float)

    cache: dict[tuple[str, str], float] = {}

    def compute(pair: tuple[Any, Any]) -> float:
        raw_origin, raw_destination = pair
        key = (str(raw_origin), str(raw_destination))
        if key in cache:
            return cache[key]
        try:
            features = station_index.pair_features(raw_origin, raw_destination)
            value = features.estimated_route_distance_m
        except (ValueError, TypeError):
            value = float("nan")
        cache[key] = value
        return value

    return pd.Series(map(compute, zip(origin, destination)), index=origin.index, dtype=float)


def preprocess_frame(
    frame: pd.DataFrame,
    *,
    station_index: StationIndex | None = None,
    low_speed_cut_kmh: float = 15.0,
    high_speed_cut_kmh: float = 25.0,
) -> tuple[pd.DataFrame, dict[str, bool]]:
    """원본 ETA 데이터를 모델 입력용 표준 테이블로 변환한다.

    ``datetime``과 ``speed_kmh``는 필요한 파생값을 만든 뒤 결과에서 제거한다.
    """
    data = canonicalize_columns(frame.copy())
    flags = {"weekday": False, "hour": False, "speed_level": False}

    missing = [column for column in REQUIRED_BASE if column not in data.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}. 현재 컬럼: {list(data.columns)}")

    parsed_datetime: pd.Series | None = None
    if "datetime" in data.columns:
        parsed_datetime = pd.to_datetime(data["datetime"], errors="coerce")

    if "weekday" not in data.columns:
        if parsed_datetime is None:
            raise ValueError("weekday 컬럼이 없으면 datetime 컬럼이 필요합니다.")
        data["weekday"] = parsed_datetime.dt.dayofweek
        flags["weekday"] = True

    if "hour" not in data.columns:
        if parsed_datetime is not None:
            data["hour"] = parsed_datetime.dt.hour
            flags["hour"] = True
        else:
            data["hour"] = 12

    if "hour_band" not in data.columns:
        data["hour_band"] = data["hour"].map(lambda value: hour_band(value) if pd.notna(value) else None)

    if "speed_level" not in data.columns:
        if "speed_kmh" not in data.columns:
            raise ValueError("speed_level 컬럼이 없으면 speed_kmh 컬럼이 필요합니다.")
        speed_numeric = pd.to_numeric(data["speed_kmh"], errors="coerce")
        data["speed_level"] = speed_numeric.map(
            lambda value: (
                speed_level_from_kmh(value, low_cut=low_speed_cut_kmh, high_cut=high_speed_cut_kmh)
                if pd.notna(value) else None
            )
        )
        flags["speed_level"] = True

    if "route_distance_m" not in data.columns:
        data["route_distance_m"] = _derive_route_distance(
            data["origin_station"], data["destination_station"], station_index
        )

    data["origin_station"] = data["origin_station"].map(lambda value: str(value).strip())
    data["destination_station"] = data["destination_station"].map(lambda value: str(value).strip())
    data["weather"] = _safe_normalize(data["weather"], normalize_weather, default="clear")
    data["weekday"] = _safe_normalize(data["weekday"], normalize_weekday)
    data["speed_level"] = _safe_normalize(data["speed_level"], normalize_speed_level)
    data["hour"] = pd.to_numeric(data["hour"], errors="coerce").round().astype("Int64")
    data["route_distance_m"] = pd.to_numeric(data["route_distance_m"], errors="coerce")
    data["travel_time_sec"] = pd.to_numeric(data["travel_time_sec"], errors="coerce")

    # 같은 정류장은 DRT 차량 이동 구간이 아니므로 학습 데이터에서 제외한다.
    valid = (
        data["origin_station"].ne("")
        & data["destination_station"].ne("")
        & data["origin_station"].map(normalize_station_name).ne(
            data["destination_station"].map(normalize_station_name)
        )
        & data["weather"].notna()
        & data["weekday"].notna()
        & data["speed_level"].notna()
        & data["hour"].between(0, 23, inclusive="both")
        & data["route_distance_m"].gt(0)
        & data["travel_time_sec"].gt(0)
        & data["travel_time_sec"].le(4 * 60 * 60)
    )
    clean = data.loc[valid, list(OUTPUT_COLUMNS)].copy()
    clean["hour"] = clean["hour"].astype(int)
    clean["route_distance_m"] = clean["route_distance_m"].round(1)
    clean["travel_time_sec"] = clean["travel_time_sec"].round(1)
    return clean, flags


def preprocess_csv(
    input_path: str | Path,
    output_path: str | Path,
    *,
    stations_path: str | Path | None = None,
    chunksize: int = 100_000,
    encoding: str = "utf-8-sig",
    report_path: str | Path | None = None,
) -> PreprocessSummary:
    """100만 행 수준 CSV도 한 번에 메모리에 올리지 않고 전처리한다."""
    source = Path(input_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    station_index = StationIndex.from_csv(stations_path) if stations_path else None
    summary = PreprocessSummary(input_path=str(source), output_path=str(target))
    write_header = True

    reader: Iterable[pd.DataFrame] = pd.read_csv(source, chunksize=chunksize, encoding=encoding, low_memory=False)
    for chunk in reader:
        summary.chunks += 1
        summary.rows_read += len(chunk)
        clean, flags = preprocess_frame(chunk, station_index=station_index)
        summary.derived_weekday = summary.derived_weekday or flags["weekday"]
        summary.derived_hour = summary.derived_hour or flags["hour"]
        summary.derived_speed_level = summary.derived_speed_level or flags["speed_level"]
        summary.rows_written += len(clean)
        clean.to_csv(
            target, mode="w" if write_header else "a", header=write_header,
            index=False, encoding="utf-8-sig" if write_header else "utf-8",
        )
        write_header = False

    summary.rows_dropped = summary.rows_read - summary.rows_written
    destination_report = Path(report_path) if report_path else target.with_suffix(".summary.json")
    destination_report.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
