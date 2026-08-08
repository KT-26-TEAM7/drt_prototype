"""도착지 후보 검색 기준점과 총 이동시간(total_travel_time_s) 계산 검증."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import app.reservation.plan_route as plan_route_module
from app.clients.tmap_client import Coordinate, MockTmapClient, POI, Route, TmapClient
from app.destination.search_by_category import (
    CATEGORY_CANDIDATE_COUNT,
    CATEGORY_INITIAL_RADIUS_M,
    category_poi_candidates,
)
from app.geo import SearchKeywordType
from app.reservation.plan_route import evaluate_poi, plan_category, plan_specific
from app.stations.find_departure_station import best_station_access, station_access_candidates
from app.travel_time.estimate_duration import ETAContext, ETAPredictor, ETAService, StationIndex

SADANG = Coordinate(37.4849, 126.9710)
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "app" / "travel_time" / "models"


@pytest.fixture
def eta_service(stations) -> ETAService:
    return ETAService(ETAPredictor(StationIndex(stations), artifacts_dir=ARTIFACTS_DIR))


@pytest.fixture
def eta_context() -> ETAContext:
    return ETAContext(weather="맑음", weekday="월요일", hour=9)


class RecordingProvider(MockTmapClient):
    """search_pois에 실제로 전달된 center 좌표를 기록하는 얇은 래퍼."""

    def __init__(self):
        self.recorded_centers: list[Coordinate] = []

    async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
        self.recorded_centers.append(center)
        return await super().search_pois(keyword, center, radius_m, count)


async def _expected_boarding_coord(stations) -> Coordinate:
    boarding = await best_station_access(SADANG, "현재 위치", stations, MockTmapClient(), 500)
    station = boarding["station"]
    return Coordinate(station.lat, station.lon)


def test_plan_category_searches_around_boarding_station_not_origin(stations, eta_service, eta_context):
    provider = RecordingProvider()
    asyncio.run(plan_category("정형외과", SADANG, stations, provider, eta_service, eta_context, 500, 300))

    expected_center = asyncio.run(_expected_boarding_coord(stations))
    assert provider.recorded_centers  # 최소 1회는 호출됨
    assert all(center == expected_center for center in provider.recorded_centers)
    assert all(center != SADANG for center in provider.recorded_centers)


def test_plan_specific_searches_around_boarding_station_not_origin(stations, eta_service, eta_context):
    provider = RecordingProvider()
    asyncio.run(plan_specific("남현서울정형외과", SADANG, stations, provider, eta_service, eta_context, 500, 300))

    expected_center = asyncio.run(_expected_boarding_coord(stations))
    assert provider.recorded_centers == [expected_center]


def test_drt_total_travel_time_is_exact_unrounded_sum(stations, eta_service, eta_context):
    """반올림 이전 원시 Route 값 기준으로 total_travel_time_s가 정확히 세 구간의 합인지 확인."""
    result = asyncio.run(
        plan_specific("남현서울정형외과", SADANG, stations, MockTmapClient(), eta_service, eta_context, 500, 300)
    )
    assert result["recommended_mode"] == "drt"
    expected = (
        result["boarding"]["walk"].duration_s
        + result["vehicle"].duration_s
        + result["alighting"]["walk"].duration_s
    )
    assert result["total_travel_time_s"] == expected


def test_walk_recommended_total_travel_time_is_exact_direct_walk(stations, eta_service, eta_context):
    result = asyncio.run(
        plan_specific("사당정형외과의원", SADANG, stations, MockTmapClient(), eta_service, eta_context, 500, 300)
    )
    assert result["recommended_mode"] == "walk"
    assert result["total_travel_time_s"] == result["direct_walk"].duration_s


def _fake_boarding_and_access(station, walk_distance_m: float):
    access = {"station": station, "walk": Route(walk_distance_m, walk_distance_m, "fixed")}

    async def fake_best_station_access(coord, name, stations_, client, walk_limit):
        return access

    return access, fake_best_station_access


class FixedWalkClient(MockTmapClient):
    """직선/실제 도로 사정과 무관하게 고정된 도보 거리를 돌려주는 테스트용 클라이언트."""

    def __init__(self, distance_m: float):
        self.distance_m = distance_m

    async def pedestrian_route(self, start, end, start_name="", end_name=""):
        return Route(self.distance_m, self.distance_m, "fixed")


def test_same_station_long_direct_walk_is_rejected_not_walk(stations, eta_service, eta_context, monkeypatch):
    """승·하차 정류장이 같아도, 실제 직접 도보 거리가 보행 한도를 넘으면 도보를 추천하면 안 된다."""
    station = stations[0]
    boarding, fake_access = _fake_boarding_and_access(station, 50)
    monkeypatch.setattr(plan_route_module, "best_station_access", fake_access)

    poi = POI("far1", "먼거리병원", Coordinate(station.lat, station.lon), "주소", 900, "mock")
    client = FixedWalkClient(900)  # 보행 한도(500m)를 넘는 직접 도보 거리

    result = asyncio.run(evaluate_poi(
        Coordinate(station.lat, station.lon), boarding, poi, "specific", stations,
        client, eta_service, eta_context, 500, 300,
    ))
    assert result["status"] == "rejected"
    assert result["recommended_mode"] == "none"


def test_same_station_short_direct_walk_still_recommends_walk(stations, eta_service, eta_context, monkeypatch):
    """보행 한도 이내라면 승·하차 정류장이 같아도 도보 추천은 그대로 유지된다."""
    station = stations[0]
    boarding, fake_access = _fake_boarding_and_access(station, 50)
    monkeypatch.setattr(plan_route_module, "best_station_access", fake_access)

    poi = POI("near1", "가까운병원", Coordinate(station.lat, station.lon), "주소", 450, "mock")
    client = FixedWalkClient(450)  # 보행 한도(500m) 이내

    result = asyncio.run(evaluate_poi(
        Coordinate(station.lat, station.lon), boarding, poi, "specific", stations,
        client, eta_service, eta_context, 500, 300,
    ))
    assert result["status"] == "walk_recommended"
    assert result["recommended_mode"] == "walk"


def test_plan_category_limits_candidates_to_three(stations, eta_service, eta_context):
    """DRT_case1.ipynb와 동일하게, 매칭되는 POI가 더 많아도 최대 3개만 실제 평가한다."""
    result = asyncio.run(
        plan_category("정형외과", SADANG, stations, MockTmapClient(), eta_service, eta_context, 500, 300)
    )
    # mock 데이터는 "정형외과"에 5곳이 매칭되지만, 후보 상한(3) 안으로 줄어야 한다.
    assert len(result["candidate_audit"]) == CATEGORY_CANDIDATE_COUNT


class RadiusAwareProvider(MockTmapClient):
    """radius_m에 따라 다른 POI 집합을 돌려주는 fake client.

    실제 mock 데이터는 3km 안에서 이미 후보 상한(3)을 채워서 확장 로직 자체를
    유도할 수 없다. 반경별로 결과 수를 직접 통제해 확장 여부를 결정적으로 검증한다.
    """

    def __init__(self):
        self.recorded_radii: list[float] = []

    async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
        self.recorded_radii.append(radius_m)
        names = ["가까운후보"] if radius_m <= CATEGORY_INITIAL_RADIUS_M else ["가까운후보", "먼후보1", "먼후보2"]
        return [
            POI(f"fake-{i}", name, Coordinate(center.lat + i * 0.001, center.lon), source="fake")
            for i, name in enumerate(names)
        ]


def test_category_poi_candidates_expands_radius_when_too_few():
    provider = RadiusAwareProvider()
    candidates, used_radius_m, radius_expanded, failures = asyncio.run(
        category_poi_candidates(provider, "아무키워드", SADANG)
    )
    assert provider.recorded_radii == [CATEGORY_INITIAL_RADIUS_M, CATEGORY_INITIAL_RADIUS_M * 2]
    assert radius_expanded is True
    assert used_radius_m == CATEGORY_INITIAL_RADIUS_M * 2
    assert len(candidates) == CATEGORY_CANDIDATE_COUNT
    assert not failures


def test_category_poi_candidates_skips_expansion_when_enough_found():
    provider = MockTmapClient()  # "정형외과"는 3km 안에서 이미 5곳 매칭 (상한보다 많음)
    _, _, radius_expanded, _ = asyncio.run(
        category_poi_candidates(provider, "정형외과", SADANG)
    )
    assert radius_expanded is False


class FailAtStationProvider(MockTmapClient):
    """특정 정류장으로의(에서의) 보행경로 조회만 실패시켜 근접 폴백을 유도한다."""

    def __init__(self, failing_station_name: str):
        self.failing_station_name = failing_station_name

    async def pedestrian_route(self, start, end, start_name="", end_name=""):
        if self.failing_station_name in (start_name, end_name):
            raise RuntimeError("TMAP 실패(근접 정류장)")
        return await super().pedestrian_route(start, end, start_name, end_name)


def test_nearby_station_fallback_used_when_walking_route_fails(stations):
    """출발지가 정류장과 겹쳐(10m 이내) 보행경로 API가 실패해도 직선거리로 대체 평가한다."""
    target = stations[0]
    provider = FailAtStationProvider(target.name)
    access = asyncio.run(
        station_access_candidates(Coordinate(target.lat, target.lon), "현재 위치", stations, provider, 500)
    )
    assert access.best is not None
    assert access.best["station"].station_id == target.station_id
    assert access.best["walk"].source == "fallback_straight_line"
    assert access.best["walk"].distance_m == 0


class KeywordTypeRecordingProvider(MockTmapClient):
    def __init__(self):
        self.recorded_keyword_types: list = []

    async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
        self.recorded_keyword_types.append(keyword_type)
        return await super().search_pois(keyword, center, radius_m, count)


def test_plan_specific_uses_exact_keyword_type(stations, eta_service, eta_context):
    provider = KeywordTypeRecordingProvider()
    asyncio.run(plan_specific("남현서울정형외과", SADANG, stations, provider, eta_service, eta_context, 500, 300))
    assert provider.recorded_keyword_types == [SearchKeywordType.EXACT]


def test_plan_category_uses_category_keyword_type(stations, eta_service, eta_context):
    provider = KeywordTypeRecordingProvider()
    asyncio.run(plan_category("정형외과", SADANG, stations, provider, eta_service, eta_context, 500, 300))
    assert provider.recorded_keyword_types
    assert all(kt is SearchKeywordType.CATEGORY for kt in provider.recorded_keyword_types)


class AmbiguousNameProvider(MockTmapClient):
    """정확히 일치하는 이름이 없는 여러 동명이인 후보를 돌려준다."""

    async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
        return [
            POI("amb-1", "가나다정형외과", center, address="주소1", source="fake"),
            POI("amb-2", "라마바정형외과", center, address="주소2", source="fake"),
        ]


class SameNameDifferentCitiesProvider(MockTmapClient):
    """이름은 정확히 같지만 실제로는 서로 다른 도시에 있는 동명 프랜차이즈 후보를 돌려준다."""

    def __init__(self, *coords: Coordinate):
        self._coords = coords

    async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
        return [
            POI(f"cand-{i}", keyword, coord, address="주소", source="fake")
            for i, coord in enumerate(self._coords)
        ]


def test_plan_specific_drops_out_of_service_area_candidates_before_confirmation(stations, eta_service, eta_context):
    """동명이지만 서비스 범위 밖(정류장 커버리지 밖)인 후보는 확인 목록에 올리지 않고,
    범위 안 후보가 하나만 남으면 바로 도보/DRT 평가로 진행한다."""
    station = stations[0]
    near = Coordinate(station.lat, station.lon)
    far_mapo = Coordinate(37.54092881, 126.94608026)  # 실제 사례: 마포구, 약 7.7km
    far_bucheon = Coordinate(37.52776135, 126.81592582)  # 실제 사례: 부천시, 약 15.5km
    provider = SameNameDifferentCitiesProvider(near, far_mapo, far_bucheon)

    result = asyncio.run(
        plan_specific("성모탑정형외과의원", SADANG, stations, provider, eta_service, eta_context, 500, 300)
    )
    assert result["status"] != "needs_destination_confirmation"
    assert result["recommended_mode"] in {"walk", "drt"}


def test_plan_specific_reports_when_all_same_name_candidates_are_outside_service_area(
    stations, eta_service, eta_context
):
    far_mapo = Coordinate(37.54092881, 126.94608026)
    far_bucheon = Coordinate(37.52776135, 126.81592582)
    provider = SameNameDifferentCitiesProvider(far_mapo, far_bucheon)

    result = asyncio.run(
        plan_specific("성모탑정형외과의원", SADANG, stations, provider, eta_service, eta_context, 500, 300)
    )
    assert result["status"] == "destination_outside_service_area"
    assert result["recommended_mode"] == "other_transit"


def test_plan_specific_needs_confirmation_returns_full_candidate_fields(stations, eta_service, eta_context):
    """동명이인 확인이 필요할 때도 candidates가 /api/destinations/name-search와 같은
    필드(주소·좌표뿐 아니라 phone/district/category 등)를 갖춰야 한다."""
    result = asyncio.run(
        plan_specific("아무개정형외과", SADANG, stations, AmbiguousNameProvider(), eta_service, eta_context, 500, 300)
    )
    assert result["status"] == "needs_destination_confirmation"
    assert len(result["candidates"]) == 2
    for candidate in result["candidates"]:
        assert set(candidate) == {
            "name", "address", "latitude", "longitude", "straight_distance_m",
            "source", "phone", "district", "neighborhood", "category", "detail_category",
        }


def test_category_poi_candidates_dedup_uses_poi_id_not_just_name_and_coord():
    """같은 이름·좌표라도 poi_id가 다르면 서로 다른 장소로 취급해야 한다."""

    class DuplicateNameProvider(MockTmapClient):
        async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
            return [
                POI("fake-a", "동명이인의원", Coordinate(center.lat, center.lon), source="fake"),
                POI("fake-b", "동명이인의원", Coordinate(center.lat, center.lon), source="fake"),
            ]

    candidates, *_ = asyncio.run(
        category_poi_candidates(DuplicateNameProvider(), "아무키워드", SADANG)
    )
    assert len(candidates) == 2


def test_parking_lot_pois_are_excluded_from_tmap_results():
    """실제 TMAP 응답 경로(TmapClient._parse_pois)에서 주차장을 제외하는지 확인."""
    body = {
        "searchPoiInfo": {"pois": {"poi": [
            {"id": "1", "name": "사당정형외과의원", "frontLat": "37.4849", "frontLon": "126.9711"},
            {"id": "2", "name": "사당정형외과의원 주차장", "frontLat": "37.4849", "frontLon": "126.9711"},
        ]}}
    }
    results = TmapClient._parse_pois(body, SADANG, radius_m=1000, count=10)
    assert [poi.name for poi in results] == ["사당정형외과의원"]
