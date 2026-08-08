"""app/destination/search_by_name.py 검증 — 특히 narrow_exact_matches가 실제로
정확매치를 우선시키는지, 그리고 search_by_name()이 이걸 자동 적용하는지 확인한다."""
from __future__ import annotations

import asyncio

from app.clients.tmap_client import Coordinate, MockTmapClient, POI
from app.destination.search_by_name import narrow_exact_matches, search_by_name

CENTER = Coordinate(37.4849, 126.9710)


def _poi(poi_id: str, name: str) -> POI:
    return POI(poi_id, name, CENTER, source="fake")


def test_narrow_exact_matches_prefers_exact_name():
    candidates = [_poi("1", "남현서울정형외과의원"), _poi("2", "남현서울정형외과")]
    narrowed = narrow_exact_matches(candidates, "남현서울정형외과")
    assert [poi.name for poi in narrowed] == ["남현서울정형외과"]


def test_narrow_exact_matches_ignores_spaces_and_case():
    candidates = [_poi("1", "남현 서울 정형외과"), _poi("2", "다른곳")]
    narrowed = narrow_exact_matches(candidates, "남현서울정형외과")
    assert [poi.name for poi in narrowed] == ["남현 서울 정형외과"]


def test_narrow_exact_matches_falls_back_to_all_when_no_exact_match():
    candidates = [_poi("1", "가나다정형외과"), _poi("2", "라마바정형외과")]
    narrowed = narrow_exact_matches(candidates, "존재하지않는이름")
    assert narrowed == candidates


class LooseMatchProvider(MockTmapClient):
    """정확명이 아니라 느슨하게(부분 일치) 여러 후보를 돌려주는 fake 클라이언트.

    실제 TMAP은 이런 경우가 흔하다 — 검색어와 완전히 같은 이름 하나와, 비슷한 이름
    여럿을 함께 돌려준다.
    """

    async def search_pois(self, keyword, center, radius_m, count=5, keyword_type=None):
        return [
            _poi("1", "남현서울정형외과"),
            _poi("2", "남현서울정형외과의원분점"),
            _poi("3", "구남현서울정형외과"),
        ]


def test_search_by_name_narrows_loose_matches_to_exact_one():
    """search_by_name()이 narrow_exact_matches를 자동 적용하므로, /api/plan과
    /api/destinations/name-search가 항상 같은 결과를 봐야 한다."""
    result = asyncio.run(search_by_name(LooseMatchProvider(), "남현서울정형외과", CENTER))
    assert result["status"] == "ok"
    assert [poi.name for poi in result["candidates"]] == ["남현서울정형외과"]
