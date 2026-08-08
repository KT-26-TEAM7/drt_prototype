from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.clients.tmap_client import Coordinate, MockTmapClient
from app.stations.find_departure_station import (
    STATION_ACCESS_CONCURRENCY,
    STATION_SHORTLIST_TOP_K,
    find_departure_station,
    shortlist_stations,
)
from tests.conftest import make_client

SADANG = Coordinate(37.4849, 126.9710)
SUWON = Coordinate(37.2861138, 127.0458013)
WALK_DELAY_S = 0.05


class BrokenProvider(MockTmapClient):
    """보행 경로 API가 전면 장애인 상황."""

    async def pedestrian_route(self, start, end, start_name="", end_name=""):
        raise RuntimeError("TMAP down")


class FlakyProvider(MockTmapClient):
    """일부 정류장만 조회에 실패하는 상황."""

    def __init__(self, failing_names: set[str]):
        self.failing_names = failing_names

    async def pedestrian_route(self, start, end, start_name="", end_name=""):
        if end_name in self.failing_names:
            raise RuntimeError("TMAP 5xx")
        return await super().pedestrian_route(start, end, start_name, end_name)


class SlowProvider(MockTmapClient):
    async def pedestrian_route(self, start, end, start_name="", end_name=""):
        await asyncio.sleep(WALK_DELAY_S)
        return await super().pedestrian_route(start, end, start_name, end_name)


def test_outside_service_area(stations):
    result = asyncio.run(find_departure_station(SUWON, stations, MockTmapClient(), 500))
    assert result["status"] == "outside_service_area"
    assert result["boarding"] is None


def test_picks_nearest_walkable_station(stations):
    result = asyncio.run(find_departure_station(SADANG, stations, MockTmapClient(), 500))
    assert result["status"] == "ok"
    assert result["boarding"]["walk"].distance_m <= 500


def test_walk_limit_excludes_all_stations(stations):
    """서비스 범위 안이어도 도보 한도가 짧으면 승차 정류장이 없다."""
    result = asyncio.run(find_departure_station(SADANG, stations, MockTmapClient(), 1))
    assert result["status"] == "no_accessible_boarding_station"


def test_route_api_failure_is_not_reported_as_no_station(stations):
    """API 장애를 '정류장 없음'으로 잘못 보고하지 않아야 한다."""
    result = asyncio.run(find_departure_station(SADANG, stations, BrokenProvider(), 500))
    assert result["status"] == "route_api_failed"
    assert result["failed_station_count"] == result["candidate_count"]
    assert result["failures"]


def test_shortlist_caps_candidates(stations):
    """정류장이 늘어도 보행 경로 API 호출은 상한을 넘지 않는다."""
    covered = shortlist_stations(SADANG, stations)
    assert len(covered) > STATION_SHORTLIST_TOP_K  # 상한이 실제로 동작하는 조건

    capped = shortlist_stations(SADANG, stations, STATION_SHORTLIST_TOP_K)
    assert capped == covered[:STATION_SHORTLIST_TOP_K]  # 가까운 순으로 남는다

    result = asyncio.run(find_departure_station(SADANG, stations, MockTmapClient(), 500))
    assert result["candidate_count"] == STATION_SHORTLIST_TOP_K


def test_service_area_check_ignores_the_cap(stations):
    """상한은 API 호출 절감용일 뿐, 서비스 범위 판정을 좁히면 안 된다."""
    result = asyncio.run(find_departure_station(SADANG, stations, MockTmapClient(), 500, top_k=1))
    assert result["status"] == "ok"
    assert result["candidate_count"] == 1

    outside = asyncio.run(find_departure_station(SUWON, stations, MockTmapClient(), 500, top_k=1))
    assert outside["status"] == "outside_service_area"


def test_partial_failure_still_returns_best_reachable_station(stations):
    candidates = shortlist_stations(SADANG, stations, STATION_SHORTLIST_TOP_K)
    failing = {station.name for station in candidates[:3]}
    provider = FlakyProvider(failing)
    result = asyncio.run(find_departure_station(SADANG, stations, provider, 500))
    assert result["status"] == "ok"
    assert result["boarding"]["station"].name not in failing
    assert result["failed_station_count"] == len(failing)


def test_result_is_deterministic(stations):
    picks = {
        asyncio.run(find_departure_station(SADANG, stations, MockTmapClient(), 500))["boarding"]["station"].station_id
        for _ in range(5)
    }
    assert len(picks) == 1


def test_station_lookups_run_in_parallel(stations):
    """상한을 풀어 후보를 늘린 뒤, 소요시간이 순차 호출보다 확실히 짧은지 본다."""
    candidate_count = len(shortlist_stations(SADANG, stations))
    assert candidate_count > STATION_ACCESS_CONCURRENCY  # 순차/병렬 차이가 드러나는 조건

    started = time.perf_counter()
    result = asyncio.run(find_departure_station(SADANG, stations, SlowProvider(), 500, top_k=None))
    elapsed = time.perf_counter() - started

    assert result["candidate_count"] == candidate_count
    serial_s = candidate_count * WALK_DELAY_S
    assert elapsed < serial_s / 2


def test_endpoint_applies_settings_walk_limit(tmp_path: Path):
    """요청이 max_walk_m을 생략하면 서버 설정값이 적용된다."""
    with make_client(tmp_path, default_max_walk_m=1) as client:
        body = client.post("/api/stations/departure", json={
            "latitude": SADANG.lat, "longitude": SADANG.lon,
        }).json()
        assert body["applied_max_walk_m"] == 1
        assert body["status"] == "no_accessible_boarding_station"

    with make_client(tmp_path / "b", default_max_walk_m=500) as client:
        body = client.post("/api/stations/departure", json={
            "latitude": SADANG.lat, "longitude": SADANG.lon,
        }).json()
        assert body["applied_max_walk_m"] == 500
        assert body["status"] == "ok"


def test_endpoint_request_overrides_settings_walk_limit(tmp_path: Path):
    with make_client(tmp_path, default_max_walk_m=500) as client:
        body = client.post("/api/stations/departure", json={
            "latitude": SADANG.lat, "longitude": SADANG.lon, "max_walk_m": 1,
        }).json()
        assert body["applied_max_walk_m"] == 1
        assert body["status"] == "no_accessible_boarding_station"


def test_endpoint_saves_location(tmp_path: Path):
    """/api/plan과 마찬가지로 출발 정류장 조회도 위치를 저장한다."""
    with make_client(tmp_path) as client:
        client.post("/api/stations/departure", json={
            "latitude": SADANG.lat, "longitude": SADANG.lon, "accuracy": 8.0,
        })
        latest = client.get("/api/location").json()
        assert latest["ok"] is True
        assert latest["location"]["latitude"] == SADANG.lat


def test_endpoint_response_is_documented(tmp_path: Path):
    """응답 계약이 OpenAPI에 노출되고 실제 응답이 그 스키마를 따른다."""
    with make_client(tmp_path) as client:
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/api/stations/departure"]["post"]["responses"]["200"]
        assert "DepartureStationResponse" in str(ref)

        body = client.post("/api/stations/departure", json={
            "latitude": SADANG.lat, "longitude": SADANG.lon,
        }).json()
        assert set(body) == {
            "status", "boarding", "reason", "applied_max_walk_m",
            "candidate_count", "failed_station_count", "failures",
        }
        assert set(body["boarding"]) == {
            "station_id", "name", "station_type", "walk_distance_m", "walk_duration_s",
        }
