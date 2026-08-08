"""app/destination/search_by_category.py (노성민 담당 래퍼) 검증."""
from __future__ import annotations

import asyncio

from app.clients.tmap_client import Coordinate, MockTmapClient
from app.destination.search_by_category import CATEGORY_CANDIDATE_COUNT, search_by_category
from app.stations.find_departure_station import best_station_access
from tests.conftest import backup_stations

SADANG = Coordinate(37.4849, 126.9710)


async def _boarding_coord() -> Coordinate:
    stations = backup_stations()
    boarding = await best_station_access(SADANG, "현재 위치", stations, MockTmapClient(), 500)
    station = boarding["station"]
    return Coordinate(station.lat, station.lon)


def test_search_by_category_returns_up_to_candidate_count():
    center = asyncio.run(_boarding_coord())
    result = asyncio.run(search_by_category(MockTmapClient(), "정형외과", center))

    assert result["status"] == "ok"
    assert result["reason"] is None
    assert 0 < len(result["candidates"]) <= CATEGORY_CANDIDATE_COUNT
    assert all(hasattr(poi, "name") and hasattr(poi, "coord") for poi in result["candidates"])


def test_search_by_category_reports_no_candidates_found():
    center = asyncio.run(_boarding_coord())
    result = asyncio.run(search_by_category(MockTmapClient(), "우주정거장", center))

    assert result["status"] == "no_candidates_found"
    assert result["candidates"] == []
    assert result["reason"]


def test_search_by_category_delegates_to_shared_algorithm():
    """search_by_category와 category_poi_candidates가 같은 알고리즘을 쓰는지 확인 —
    후보 이름이 일치해야 한다."""
    from app.destination.search_by_category import category_poi_candidates

    center = asyncio.run(_boarding_coord())
    wrapper_result = asyncio.run(search_by_category(MockTmapClient(), "정형외과", center))
    direct_candidates, *_ = asyncio.run(
        category_poi_candidates(MockTmapClient(), "정형외과", center)
    )

    assert [poi.name for poi in wrapper_result["candidates"]] == [poi.name for poi in direct_candidates]
