"""노성민, 장인영 담당: 목적지 좌표 -> 하차(도착) 정류장 결정 (case1/2 공용).

find_departure_station.py의 station_access_candidates를 재사용한다. 방향(사용자→정류장 vs
정류장→목적지)에 따른 보행경로 차이는 다루지 않는다 — app/reservation/plan_route.py가 하차
정류장을 계산할 때도 이미 동일한 방식(목적지 좌표를 point로 넘기는 방식)을 쓰고 있어, 그
기존 동작과 일관성을 유지한다.
"""
from __future__ import annotations

from app.clients.tmap_client import Coordinate, MockTmapClient, TmapClient
from app.db.models import Station
from app.stations.find_departure_station import (
    DEFAULT_WALK_LIMIT_M,
    MAX_REPORTED_FAILURES,
    STATION_SHORTLIST_TOP_K,
    station_access_candidates,
)


async def find_arrival_station(
    destination: Coordinate,
    destination_name: str,
    stations: list[Station],
    client: TmapClient | MockTmapClient,
    user_walk_limit_m: float = DEFAULT_WALK_LIMIT_M,
    top_k: int | None = STATION_SHORTLIST_TOP_K,
) -> dict:
    access = await station_access_candidates(
        destination, destination_name, stations, client, user_walk_limit_m, top_k
    )
    if access.candidate_count == 0:
        return {
            "status": "outside_service_area",
            "alighting": None,
            "reason": "목적지가 DRT 서비스 범위 밖입니다.",
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
            "alighting": None,
            "reason": "보행 경로 조회에 실패해 하차 정류장을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
            **diagnostics,
        }
    if access.best is None:
        return {
            "status": "no_accessible_alighting_station",
            "alighting": None,
            "reason": "목적지가 서비스 지역 안이지만 보행 한도 내 하차 정류장이 없습니다.",
            **diagnostics,
        }
    return {
        "status": "ok",
        "alighting": access.best,
        "reason": None,
        **diagnostics,
    }
