"""SQLAlchemy 엔진/세션 및 정류장·위치·예약 CRUD 헬퍼.

`database_path`가 요청(Settings)마다 달라질 수 있어(테스트에서는 매번 임시 파일) 엔진을
모듈 전역으로 한 번만 만들지 않고, `create_engine_and_sessionmaker()`로 앱 기동 시
`app.state`에 만들어 넣는다(`app/main.py` 참고). 라우트는 `get_db()` 의존성으로 세션을 받는다.
"""
from __future__ import annotations

import csv
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, LocationPing, Reservation, Station

# 정류장별 커버리지 반경(m)/도보 한도(m) 튜닝값. 없으면 DEFAULT_* 사용.
STATION_TUNING: dict[int, tuple[float, float]] = {
    1: (700, 500), 2: (650, 500), 3: (550, 450), 5: (600, 500), 6: (600, 450),
    9: (700, 500), 11: (500, 400), 12: (500, 400), 13: (650, 500), 14: (700, 500),
    15: (550, 450), 17: (800, 550), 19: (700, 500), 20: (600, 500),
    4: (700, 500), 7: (700, 500), 8: (700, 500),
    10: (700, 500), 16: (700, 500), 18: (700, 500),
}
DEFAULT_COVERAGE_RADIUS_M = 700.0
DEFAULT_WALK_LIMIT_M = 500.0

# ext_id: 외부(기존 대중교통) 연동 ID. "DRT가상" 정류장은 실제 정류장이 아니므로 없음(None).
BACKUP_STATIONS_RAW = [
    (1, "사당종합체육관", "기존", 37.49284821, 126.9696768, "20534"),
    (2, "동작삼일수영장", "기존", 37.48730095, 126.9745083, "20559"),
    (3, "남성역", "기존", 37.48479351, 126.9709102, "20178"),
    (4, "사당솔밭도서관", "기존", 37.484, 126.9671, "20727"),
    (5, "동작고등학교", "기존", 37.48256382, 126.9653687, "20568"),
    (6, "레미안로이파크아파트", "기존", 37.48810702, 126.9730211, "20751"),
    (7, "사당중학교", "기존", 37.4866, 126.9682, "20177"),
    (8, "사당키움센터(KCC아파트)", "DRT가상", 37.4818, 126.9738, None),
    (9, "사당종합복지관", "DRT가상", 37.47701696, 126.9798513, None),
    (10, "한옥카페R1", "DRT가상", 37.4805, 126.9679, None),
    (11, "제일아파트", "DRT가상", 37.48292988, 126.9695225, None),
    (12, "사당커뮤니티센터", "DRT가상", 37.48140732, 126.9701065, None),
    (13, "사당4동주민센터", "DRT가상", 37.48148062, 126.9753865, None),
    (14, "사당4동행정복지센터", "DRT가상", 37.4887525, 126.9792534, None),
    (15, "청소년독서실", "DRT가상", 37.4804836, 126.9731007, None),
    (16, "진흥아리엘아파트", "DRT가상", 37.4804, 126.9694, None),
    (17, "사당현대아이파크", "DRT가상", 37.49160414, 126.9848386, None),
    (18, "사당삼익그린뷰아파트(정문)", "DRT가상", 37.4774, 126.9692, None),
    (19, "사당롯데캐슬샤인아파트", "DRT가상", 37.49077659, 126.9725136, None),
    (20, "남성중학교", "DRT가상", 37.47904544, 126.972441, None),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tuning_for(station_id: int) -> tuple[float, float]:
    return STATION_TUNING.get(station_id, (DEFAULT_COVERAGE_RADIUS_M, DEFAULT_WALK_LIMIT_M))


def _pick(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return value
    return ""


def parse_stations_csv(csv_path: str | Path) -> list[dict]:
    rows: list[dict] = []
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as stream:
        for raw in csv.DictReader(stream):
            row = {(key or "").strip().lower(): (value or "").strip() for key, value in raw.items() if key}
            station_id_raw = _pick(row, "id", "station_id")
            lat_raw = _pick(row, "lat", "latitude")
            lon_raw = _pick(row, "lon", "longitude", "lng")
            if not station_id_raw or not lat_raw or not lon_raw:
                continue
            try:
                station_id = int(station_id_raw)
                lat, lon = float(lat_raw), float(lon_raw)
            except ValueError:
                continue
            coverage, walk_limit = tuning_for(station_id)
            rows.append({
                "station_id": station_id,
                "name": _pick(row, "name", "station_name") or f"정류장{station_id}",
                "station_type": _pick(row, "type", "station_type"),
                "lat": lat,
                "lon": lon,
                "coverage_radius_m": coverage,
                "walk_limit_m": walk_limit,
                "ext_id": _pick(row, "ext_id") or None,
            })
    return rows


def station_rows_from_backup() -> list[dict]:
    rows = []
    for station_id, name, station_type, lat, lon, ext_id in BACKUP_STATIONS_RAW:
        coverage, walk_limit = tuning_for(station_id)
        rows.append({
            "station_id": station_id,
            "name": name,
            "station_type": station_type,
            "lat": lat,
            "lon": lon,
            "coverage_radius_m": coverage,
            "walk_limit_m": walk_limit,
            "ext_id": ext_id,
        })
    return rows


def create_engine_and_sessionmaker(database_path: Path) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def seed_stations_if_empty(session: AsyncSession, stations_csv_path: Path) -> int:
    count = await session.scalar(select(func.count()).select_from(Station))
    if count:
        return 0
    return await import_stations(session, stations_csv_path)


async def import_stations(session: AsyncSession, stations_csv_path: Path | None = None) -> int:
    rows = (
        parse_stations_csv(stations_csv_path)
        if stations_csv_path and stations_csv_path.exists()
        else station_rows_from_backup()
    )
    now = _utc_now_iso()
    for row in rows:
        stmt = sqlite_insert(Station).values(
            station_id=row["station_id"],
            name=row["name"],
            station_type=row["station_type"],
            lat=row["lat"],
            lon=row["lon"],
            coverage_radius_m=row["coverage_radius_m"],
            walk_limit_m=row["walk_limit_m"],
            ext_id=row.get("ext_id"),
            is_active=1,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["station_id"],
            set_={
                "name": stmt.excluded.name,
                "station_type": stmt.excluded.station_type,
                "lat": stmt.excluded.lat,
                "lon": stmt.excluded.lon,
                "coverage_radius_m": stmt.excluded.coverage_radius_m,
                "walk_limit_m": stmt.excluded.walk_limit_m,
                "ext_id": stmt.excluded.ext_id,
                "is_active": 1,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)
    await session.commit()
    return len(rows)


async def load_active_stations(session: AsyncSession) -> list[Station]:
    result = await session.execute(
        select(Station).where(Station.is_active == 1).order_by(Station.station_id)
    )
    return list(result.scalars().all())


async def get_station_by_id(session: AsyncSession, station_id: int) -> Station | None:
    result = await session.execute(
        select(Station).where(Station.station_id == station_id, Station.is_active == 1)
    )
    return result.scalars().first()


async def save_location_ping(
    session: AsyncSession,
    latitude: float,
    longitude: float,
    accuracy: float | None,
    captured_at: str | None,
) -> int:
    ping = LocationPing(
        latitude=latitude, longitude=longitude, accuracy=accuracy,
        captured_at=captured_at, created_at=_utc_now_iso(),
    )
    session.add(ping)
    await session.commit()
    await session.refresh(ping)
    return ping.id


async def get_latest_location(session: AsyncSession) -> dict | None:
    result = await session.execute(
        select(LocationPing).order_by(LocationPing.created_at.desc(), LocationPing.id.desc()).limit(1)
    )
    row = result.scalars().first()
    if row is None:
        return None
    return {
        "latitude": row.latitude,
        "longitude": row.longitude,
        "accuracy": row.accuracy,
        "captured_at": row.captured_at,
        "created_at": row.created_at,
    }


async def save_reservation(
    session: AsyncSession,
    call_id: str,
    status: str,
    boarding_station_id: int,
    alighting_station_id: int,
    expected_wait_s: float | None,
    requested_at: str,
) -> int:
    reservation = Reservation(
        call_id=call_id,
        status=status,
        boarding_station_id=boarding_station_id,
        alighting_station_id=alighting_station_id,
        expected_wait_s=expected_wait_s,
        requested_at=requested_at,
        created_at=_utc_now_iso(),
    )
    session.add(reservation)
    await session.commit()
    await session.refresh(reservation)
    return reservation.id
