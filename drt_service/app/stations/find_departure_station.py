"""이형주 담당: 사용자 좌표 -> 출발(승차) 정류장 결정.

정류장 커버리지 반경 필터링(`shortlist_stations`)과 병렬 보행경로 조회
(`station_access_candidates`)는 "정류장 탐색" 책임이라 이 파일에 두고,
`find_arrival_station.py`(case1/2 공용)와 `app/reservation/plan_route.py`(하차 정류장 조회)가
가져다 쓴다.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field

from app.clients.tmap_client import Coordinate, MockTmapClient, Route, TmapClient
from app.db.models import Station
from app.geo import haversine_m

STATION_ACCESS_CONCURRENCY = 8
STATION_SHORTLIST_TOP_K = 5
DEFAULT_WALK_LIMIT_M = 500.0
MAX_REPORTED_FAILURES = 5
# 출발지/목적지와 정류장이 아주 가까우면 TMAP 보행경로 API가 실패하는 경우가 있어,
# 이 거리(m) 이내면 직선거리 기반 대체 경로로 평가에서 누락되지 않게 한다.
NEARBY_STOP_FALLBACK_DISTANCE_M = 10
WALKING_SPEED_M_PER_SECOND = 1.25


def shortlist_stations(
    point: Coordinate,
    stations: list[Station],
    top_k: int | None = None,
) -> list[Station]:
    """커버리지 반경 안의 정류장을 직선거리 순으로 반환한다.

    `top_k`를 주면 가까운 순으로 그 개수만 남긴다. 정류장 수가 늘어도 뒤따르는
    보행 경로 API 호출이 선형으로 증가하지 않게 하는 상한이다.
    """
    measured = sorted(
        (
            (haversine_m(point.lat, point.lon, station.lat, station.lon), station)
            for station in stations
        ),
        key=lambda pair: (pair[0], pair[1].station_id),
    )
    covered = [
        station for distance_m, station in measured
        if distance_m <= station.coverage_radius_m
    ]
    return covered[:top_k] if top_k is not None else covered


def is_inside_service_area(point: Coordinate, stations: list[Station]) -> bool:
    """서비스 범위 판정에는 상한을 걸지 않는다(후보 상한은 API 호출 절감용일 뿐)."""
    return bool(shortlist_stations(point, stations))


@dataclass(frozen=True)
class StationAccess:
    """정류장 접근 조회 결과. 호출부가 '범위 밖'·'도보 한도 밖'·'API 장애'를 구분한다."""

    best: dict | None = None
    candidate_count: int = 0
    failures: list[str] = field(default_factory=list)


async def station_access_candidates(
    point: Coordinate,
    point_name: str,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    user_walk_limit_m: float,
    top_k: int | None = STATION_SHORTLIST_TOP_K,
) -> StationAccess:
    """후보 정류장별 보행 경로를 병렬 조회해 최적 접근과 실패 사유를 반환한다."""
    candidates = shortlist_stations(point, stations, top_k)
    if not candidates:
        return StationAccess()

    semaphore = asyncio.Semaphore(STATION_ACCESS_CONCURRENCY)

    async def walk_route(station: Station) -> Route:
        async with semaphore:
            return await client.pedestrian_route(
                point, Coordinate(station.lat, station.lon), point_name, station.name
            )

    routes = await asyncio.gather(
        *(walk_route(station) for station in candidates), return_exceptions=True
    )

    best: dict | None = None
    failures: list[str] = []
    for station, route in zip(candidates, routes):
        if isinstance(route, BaseException):
            straight_m = haversine_m(point.lat, point.lon, station.lat, station.lon)
            if straight_m > NEARBY_STOP_FALLBACK_DISTANCE_M:
                failures.append(f"{station.name}: {type(route).__name__}: {route}")
                continue
            route = Route(
                distance_m=straight_m,
                duration_s=math.ceil(straight_m / WALKING_SPEED_M_PER_SECOND),
                source="fallback_straight_line",
            )
            failures.append(f"{station.name}: 근접 정류장 폴백 사용(직선거리 {straight_m:.1f}m)")
        if route.distance_m > min(user_walk_limit_m, station.walk_limit_m):
            continue
        candidate_key = (route.duration_s, route.distance_m, station.station_id)
        if best is None or candidate_key < (
            best["walk"].duration_s, best["walk"].distance_m, best["station"].station_id
        ):
            best = {"station": station, "walk": route}
    return StationAccess(best=best, candidate_count=len(candidates), failures=failures)


async def best_station_access(
    point: Coordinate,
    point_name: str,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    user_walk_limit_m: float,
) -> dict | None:
    access = await station_access_candidates(point, point_name, stations, client, user_walk_limit_m)
    return access.best


async def find_departure_station(
    origin: Coordinate,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    user_walk_limit_m: float = DEFAULT_WALK_LIMIT_M,
    top_k: int | None = STATION_SHORTLIST_TOP_K,
) -> dict:
    access = await station_access_candidates(
        origin, "현재 위치", stations, client, user_walk_limit_m, top_k
    )
    if access.candidate_count == 0:
        return {
            "status": "outside_service_area",
            "boarding": None,
            "reason": "현재 위치가 DRT 서비스 범위 밖입니다.",
        }

    diagnostics = {
        "candidate_count": access.candidate_count,
        "failed_station_count": len(access.failures),
    }
    if access.failures:
        diagnostics["failures"] = access.failures[:MAX_REPORTED_FAILURES]

    if access.best is None and access.failures:
        return {
            "status": "route_api_failed",
            "boarding": None,
            "reason": "보행 경로 조회에 실패해 승차 정류장을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            **diagnostics,
        }
    if access.best is None:
        return {
            "status": "no_accessible_boarding_station",
            "boarding": None,
            "reason": "서비스 지역 안이지만 보행 한도 내 승차 정류장이 없습니다.",
            **diagnostics,
        }
    return {
        "status": "ok",
        "boarding": access.best,
        "reason": None,
        **diagnostics,
    }
