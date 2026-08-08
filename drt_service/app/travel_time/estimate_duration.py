"""한태희 담당: 출발·도착 정류장 간 DRT 소요시간 반환.

정규화(normalization) + 정류장 쌍 특성(station index) + 예측기(predictor)를 한 파일로
합쳤다(원래 한태희 ETA 프로젝트에서는 여러 파일이었지만, 목표 폴더 구조가 이 부분을
estimate_duration.py 한 파일로 명시했다). 학습(train_model.py)과 전처리
(preprocess_dataset.py)는 별도 파일이다.

예측은 학습 모델 → 규칙 기반 속도등급 → 거리 기반 공식 순으로 폴백한다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.db.models import Station
from app.db.session import parse_stations_csv
from app.geo import haversine_m

# ── 정규화 ──────────────────────────────────────────────────────────────

WEATHER_ALIASES: dict[str, str] = {
    "맑음": "clear", "맑은": "clear", "쾌청": "clear", "sunny": "clear", "clear": "clear",
    "흐림": "cloudy", "구름": "cloudy", "구름많음": "cloudy", "cloudy": "cloudy", "overcast": "cloudy",
    "비": "rain", "비옴": "rain", "강우": "rain", "rain": "rain", "rainy": "rain",
    "눈": "snow", "눈옴": "snow", "강설": "snow", "snow": "snow", "snowy": "snow",
}

WEEKDAY_ALIASES: dict[str, str] = {
    "월": "mon", "월요일": "mon", "monday": "mon", "mon": "mon",
    "화": "tue", "화요일": "tue", "tuesday": "tue", "tue": "tue",
    "수": "wed", "수요일": "wed", "wednesday": "wed", "wed": "wed",
    "목": "thu", "목요일": "thu", "thursday": "thu", "thu": "thu",
    "금": "fri", "금요일": "fri", "friday": "fri", "fri": "fri",
    "토": "sat", "토요일": "sat", "saturday": "sat", "sat": "sat",
    "일": "sun", "일요일": "sun", "sunday": "sun", "sun": "sun",
}

SPEED_LEVEL_ALIASES: dict[str, str] = {
    "하": "low", "낮음": "low", "느림": "low", "low": "low", "l": "low",
    "중": "medium", "보통": "medium", "medium": "medium", "mid": "medium", "m": "medium",
    "상": "high", "높음": "high", "빠름": "high", "high": "high", "h": "high",
}

SPEED_LEVEL_KO = {"low": "하", "medium": "중", "high": "상"}


def normalize_station_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _normalized_key(value: Any) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip().lower())


def normalize_weather(value: Any) -> str:
    key = _normalized_key(value)
    if not key:
        return "clear"
    return WEATHER_ALIASES.get(key, key)


def normalize_weekday(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        index = int(value)
        if 0 <= index <= 6:
            return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[index]
        if 1 <= index <= 7:
            return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[index - 1]
    key = _normalized_key(value)
    if key in WEEKDAY_ALIASES:
        return WEEKDAY_ALIASES[key]
    raise ValueError(f"지원하지 않는 요일 값입니다: {value!r}")


def normalize_speed_level(value: Any) -> str:
    key = _normalized_key(value)
    if key in SPEED_LEVEL_ALIASES:
        return SPEED_LEVEL_ALIASES[key]
    raise ValueError(f"속도 수준은 상/중/하 중 하나여야 합니다: {value!r}")


def speed_level_from_kmh(speed_kmh: float, *, low_cut: float = 15.0, high_cut: float = 25.0) -> str:
    speed = float(speed_kmh)
    if speed < low_cut:
        return "low"
    if speed < high_cut:
        return "medium"
    return "high"


def hour_band(hour: int | float) -> str:
    value = int(hour) % 24
    if 7 <= value <= 9:
        return "morning_peak"
    if 17 <= value <= 19:
        return "evening_peak"
    if 10 <= value <= 16:
        return "daytime"
    if 20 <= value <= 23:
        return "evening"
    return "night"


# ── 정류장 쌍 특성 ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StationPairFeatures:
    origin: Station
    destination: Station
    straight_distance_m: float
    estimated_route_distance_m: float


class StationIndex:
    """정류장 이름/ID 조회 및 정류장 쌍 거리 특성 계산."""

    def __init__(self, stations: list[Station], *, route_factor: float = 1.30) -> None:
        self.stations = list(stations)
        if not self.stations:
            raise ValueError("DRT 정류장 목록이 비어 있습니다.")
        self.route_factor = float(route_factor)
        self._by_id = {str(station.station_id): station for station in self.stations}
        self._by_name = {normalize_station_name(station.name): station for station in self.stations}

    @classmethod
    def from_csv(cls, path: str | Path, *, route_factor: float = 1.30) -> "StationIndex":
        rows = parse_stations_csv(path)
        stations = [
            Station(
                station_id=row["station_id"], name=row["name"], station_type=row["station_type"],
                lat=row["lat"], lon=row["lon"], coverage_radius_m=row["coverage_radius_m"],
                walk_limit_m=row["walk_limit_m"], ext_id=row.get("ext_id"),
            )
            for row in rows
        ]
        return cls(stations, route_factor=route_factor)

    def resolve(self, value: str | int) -> Station:
        raw = str(value).strip()
        if raw in self._by_id:
            return self._by_id[raw]
        key = normalize_station_name(raw)
        if key in self._by_name:
            return self._by_name[key]

        # 발표·통합 과정에서 "남성역 정류장"처럼 접미사가 붙는 경우를 허용한다.
        trimmed = key.removesuffix("drt정류장").removesuffix("정류장")
        candidates = [
            station
            for name, station in self._by_name.items()
            if trimmed and (name == trimmed or name in trimmed or trimmed in name)
        ]
        unique = {candidate.station_id: candidate for candidate in candidates}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            names = ", ".join(sorted(station.name for station in unique.values()))
            raise ValueError(f"정류장 이름이 모호합니다: {value!r} -> {names}")
        raise ValueError(f"등록되지 않은 DRT 정류장입니다: {value!r}")

    def pair_features(self, origin: str | int, destination: str | int) -> StationPairFeatures:
        start = self.resolve(origin)
        end = self.resolve(destination)
        straight = haversine_m(start.lat, start.lon, end.lat, end.lon)
        return StationPairFeatures(
            origin=start,
            destination=end,
            straight_distance_m=straight,
            estimated_route_distance_m=straight * self.route_factor,
        )


# ── 예측기 ──────────────────────────────────────────────────────────────

# train_model.py에서 회귀/분류 학습에 실제 쓰는 피처 목록과 반드시 같아야 한다.
REG_FEATURES = ["origin_station", "destination_station", "weather", "weekday", "hour_band", "speed_level", "hour", "route_distance_m"]
CLASS_FEATURES = ["weather", "weekday", "hour_band", "hour"]


@dataclass(frozen=True, slots=True)
class ETAEstimate:
    origin_station_id: int
    origin_station: str
    destination_station_id: int
    destination_station: str
    weather: str
    weekday: str
    hour: int
    speed_level: str
    speed_level_ko: str
    speed_level_source: str
    speed_confidence: float | None
    route_distance_m: float
    travel_time_sec: float
    travel_time_min: float
    lower_bound_sec: float
    upper_bound_sec: float
    prediction_source: str
    model_dataset: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ETAPredictor:
    """학습 모델 → 테이블 → 거리 기반 공식 순으로 DRT 이동시간을 반환한다."""

    def __init__(self, station_index: StationIndex, *, artifacts_dir: str | Path | None = None) -> None:
        self.station_index = station_index
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.manifest: dict[str, Any] = {}
        self.regressor_bundle: dict[str, Any] | None = None
        self.classifier_bundle: dict[str, Any] | None = None
        self.load_error: str | None = None
        if self.artifacts_dir:
            self._load_artifacts()

    @property
    def dataset_label(self) -> str:
        return str(self.manifest.get("dataset_label") or "formula_only")

    @property
    def model_ready(self) -> bool:
        return self.regressor_bundle is not None

    def _load_artifacts(self) -> None:
        assert self.artifacts_dir is not None
        manifest_path = self.artifacts_dir / "model_manifest.json"
        if not manifest_path.exists():
            self.load_error = f"모델 매니페스트 없음: {manifest_path}"
            return
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            reg_path = self.artifacts_dir / self.manifest["selected_regressor"]["path"]
            clf_path = self.artifacts_dir / self.manifest["selected_classifier"]["path"]
            self.regressor_bundle = joblib.load(reg_path)
            self.classifier_bundle = joblib.load(clf_path)
        except Exception as exc:  # 모델 라이브러리 미설치·파일 손상 시 서비스는 공식 폴백으로 유지
            self.load_error = f"ETA 모델 로드 실패: {exc}"
            self.regressor_bundle = None
            self.classifier_bundle = None

    @staticmethod
    def _probability_confidence(model: Any, frame: pd.DataFrame) -> float | None:
        try:
            proba = np.asarray(model.predict_proba(frame), dtype=float)
            if proba.size:
                return float(np.max(proba[0]))
        except Exception:
            return None
        return None

    def predict_speed_level(self, *, weather: str, weekday: str, hour: int) -> tuple[str, str, float | None]:
        normalized_weather = normalize_weather(weather)
        normalized_weekday = normalize_weekday(weekday)
        hour_value = int(hour) % 24
        row = pd.DataFrame([{
            "weather": normalized_weather, "weekday": normalized_weekday,
            "hour_band": hour_band(hour_value), "hour": hour_value,
        }])
        if self.classifier_bundle is not None:
            model = self.classifier_bundle["model"]
            try:
                raw = np.asarray(model.predict(row[CLASS_FEATURES])).reshape(-1)[0]
                level = normalize_speed_level(raw)
                confidence = self._probability_confidence(model, row[CLASS_FEATURES])
                return level, f"{self.classifier_bundle['kind']}_classifier", confidence
            except Exception as exc:
                self.load_error = f"속도 분류 예측 실패: {exc}"

        # 모델이 없을 때도 같은 입력은 같은 결과가 되도록 결정적 규칙을 사용한다.
        peak = hour_band(hour_value) in {"morning_peak", "evening_peak"}
        if normalized_weather == "snow":
            return "low", "rule_fallback", None
        if normalized_weather == "rain" or peak:
            return "medium", "rule_fallback", None
        if normalized_weekday in {"sat", "sun"} and not peak:
            return "high", "rule_fallback", None
        return "medium", "rule_fallback", None

    @staticmethod
    def _formula_seconds(route_distance_m: float, speed_level: str, weather: str) -> float:
        speed_kmh = {"low": 13.0, "medium": 20.0, "high": 28.0}[speed_level]
        weather_factor = {"clear": 1.0, "cloudy": 0.97, "rain": 0.90, "snow": 0.75}.get(weather, 0.95)
        effective_kmh = max(6.0, speed_kmh * weather_factor)
        seconds = route_distance_m / (effective_kmh * 1000 / 3600)
        # 짧은 구간의 승하차·교차로 영향을 반영한 고정 오프셋
        return max(60.0, seconds + 45.0)

    def estimate(
        self,
        *,
        origin_station: str | int,
        destination_station: str | int,
        weather: str,
        weekday: str,
        speed_level: str | None = None,
        hour: int = 12,
    ) -> ETAEstimate:
        pair = self.station_index.pair_features(origin_station, destination_station)
        normalized_weather = normalize_weather(weather)
        normalized_weekday = normalize_weekday(weekday)
        hour_value = int(hour) % 24

        if pair.origin.station_id == pair.destination.station_id:
            return ETAEstimate(
                origin_station_id=pair.origin.station_id, origin_station=pair.origin.name,
                destination_station_id=pair.destination.station_id, destination_station=pair.destination.name,
                weather=normalized_weather, weekday=normalized_weekday, hour=hour_value,
                speed_level="medium", speed_level_ko="중", speed_level_source="same_station",
                speed_confidence=1.0, route_distance_m=0.0, travel_time_sec=0.0, travel_time_min=0.0,
                lower_bound_sec=0.0, upper_bound_sec=0.0, prediction_source="same_station",
                model_dataset=self.dataset_label,
            )

        if speed_level is None:
            level, level_source, confidence = self.predict_speed_level(
                weather=normalized_weather, weekday=normalized_weekday, hour=hour_value,
            )
        else:
            level = normalize_speed_level(speed_level)
            level_source = "request_input"
            confidence = 1.0

        row = pd.DataFrame([{
            "origin_station": pair.origin.name, "destination_station": pair.destination.name,
            "weather": normalized_weather, "weekday": normalized_weekday,
            "hour_band": hour_band(hour_value), "speed_level": level, "hour": hour_value,
            "route_distance_m": pair.estimated_route_distance_m,
        }])

        prediction_source = "distance_formula_fallback"
        predicted = self._formula_seconds(pair.estimated_route_distance_m, level, normalized_weather)
        mae = max(30.0, predicted * 0.15)
        if self.regressor_bundle is not None:
            bundle = self.regressor_bundle
            try:
                model = bundle["model"]
                predicted = float(np.asarray(model.predict(row[REG_FEATURES])).reshape(-1)[0])
                prediction_source = f"{bundle['kind']}_regressor"
                selected_metrics = self.manifest.get("selected_regressor", {}).get("metrics", {})
                mae = float(selected_metrics.get("mae_s") or mae)
            except Exception as exc:
                self.load_error = f"이동시간 회귀 예측 실패: {exc}"

        # 비정상 예측값 방어: 정류장 간 DRT 구간은 30초~2시간으로 제한한다.
        predicted = min(2 * 60 * 60, max(30.0, float(predicted)))
        lower = max(0.0, predicted - 1.5 * mae)
        upper = min(3 * 60 * 60, predicted + 1.5 * mae)
        return ETAEstimate(
            origin_station_id=pair.origin.station_id, origin_station=pair.origin.name,
            destination_station_id=pair.destination.station_id, destination_station=pair.destination.name,
            weather=normalized_weather, weekday=normalized_weekday, hour=hour_value,
            speed_level=level, speed_level_ko=SPEED_LEVEL_KO[level], speed_level_source=level_source,
            speed_confidence=confidence, route_distance_m=round(pair.estimated_route_distance_m, 1),
            travel_time_sec=round(predicted, 1), travel_time_min=round(predicted / 60, 1),
            lower_bound_sec=round(lower, 1), upper_bound_sec=round(upper, 1),
            prediction_source=prediction_source, model_dataset=self.dataset_label,
        )


# ── 서비스 계층(전체 ETA = 보행+대기+DRT+보행) ───────────────────────────


@dataclass(frozen=True, slots=True)
class ETAContext:
    weather: str = "clear"
    weekday: str | int = "mon"
    speed_level: str | None = None
    hour: int = 12


class ETAService:
    """정류장 간 DRT 차량 소요시간 예측 진입점.

    보행+대기+차량+보행 합산(전체 ETA)은 app/reservation/plan_route.py가
    `total_travel_time_s`로 직접 계산하므로 여기서는 차량 구간만 다룬다.
    """

    def __init__(self, predictor: ETAPredictor) -> None:
        self.predictor = predictor

    def estimate_drt(self, **kwargs: Any) -> ETAEstimate:
        return self.predictor.estimate(**kwargs)
