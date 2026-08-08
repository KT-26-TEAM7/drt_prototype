"""노성민 담당: 대분류 검색어 -> 출발 정류장 기준 도착지 후보(최대 3개).

DRT_case1.ipynb(대분류 검색 프로토타입)의 반경/후보수 규칙을 반영한다: 3km 검색 → 후보
부족하면 반경을 한 번만 2배로 넓혀 재검색 → 출발 정류장 기준 가까운 순으로 최대 3개만
반환한다. 각 후보에 대한 승·하차 정류장 결정·도보/DRT 비교(evaluate_poi)는 이 파일의 범위
밖이며, app/reservation/plan_route.py가 이어서 처리한다.
"""
from __future__ import annotations

from app.clients.tmap_client import Coordinate, MockTmapClient, POI, TmapClient
from app.geo import SearchKeywordType, haversine_m

CATEGORY_INITIAL_RADIUS_M = 3000
CATEGORY_CANDIDATE_COUNT = 3
CATEGORY_RADIUS_EXPAND_FACTOR = 2.0
CATEGORY_POI_FETCH_COUNT = 30


async def category_poi_candidates(
    client: TmapClient | MockTmapClient,
    query: str,
    center: Coordinate,
    *,
    initial_radius_m: float = CATEGORY_INITIAL_RADIUS_M,
    candidate_count: int = CATEGORY_CANDIDATE_COUNT,
    radius_expand_factor: float = CATEGORY_RADIUS_EXPAND_FACTOR,
    fetch_count: int = CATEGORY_POI_FETCH_COUNT,
) -> tuple[list[POI], float, bool, list[dict]]:
    """대분류 검색 후보를 좁힌다. DRT_case1.ipynb의 search_case1_poi_candidates와 동일한 규칙.

    초기 반경으로 검색하고, 매칭된 POI가 candidate_count개 미만이면 반경을
    한 번만 확장해 재검색·병합한다. 최종적으로 center 기준 가까운 순으로
    candidate_count개만 반환한다.
    """
    all_candidates: dict[tuple, POI] = {}
    search_failures: list[dict] = []

    async def _search(radius_m: float) -> None:
        try:
            results = await client.search_pois(
                query, center, radius_m, fetch_count, keyword_type=SearchKeywordType.CATEGORY
            )
        except Exception as exc:
            search_failures.append({
                "status": "poi_search_failed", "radius_m": radius_m,
                "reason": f"{type(exc).__name__}: {exc}",
            })
            return
        for poi in results:
            key = (poi.poi_id, poi.name, round(poi.coord.lat, 6), round(poi.coord.lon, 6))
            all_candidates[key] = poi

    await _search(initial_radius_m)

    used_radius_m = initial_radius_m
    radius_expanded = False

    if len(all_candidates) < candidate_count:
        expanded_radius_m = initial_radius_m * radius_expand_factor
        radius_expanded = True
        used_radius_m = expanded_radius_m
        await _search(expanded_radius_m)

    ordered = sorted(
        all_candidates.values(),
        key=lambda poi: (haversine_m(center.lat, center.lon, poi.coord.lat, poi.coord.lon), poi.name),
    )
    return ordered[:candidate_count], used_radius_m, radius_expanded, search_failures


async def search_by_category(
    client: TmapClient | MockTmapClient,
    query: str,
    departure_station_coord: Coordinate,
    *,
    candidate_count: int = CATEGORY_CANDIDATE_COUNT,
    initial_radius_m: float = CATEGORY_INITIAL_RADIUS_M,
    radius_expand_factor: float = CATEGORY_RADIUS_EXPAND_FACTOR,
) -> dict:
    """대분류 검색어(예: "정형외과")로 출발 정류장 좌표 기준 도착지 후보를 찾는다."""
    candidates, used_radius_m, radius_expanded, search_failures = await category_poi_candidates(
        client,
        query,
        departure_station_coord,
        candidate_count=candidate_count,
        initial_radius_m=initial_radius_m,
        radius_expand_factor=radius_expand_factor,
    )

    if not candidates:
        return {
            "status": "no_candidates_found",
            "candidates": [],
            "reason": "출발 정류장 주변에서 검색어에 맞는 목적지를 찾지 못했습니다.",
            "used_radius_m": used_radius_m,
            "radius_expanded": radius_expanded,
            "search_failures": search_failures,
        }

    return {
        "status": "ok",
        "candidates": candidates,
        "reason": None,
        "used_radius_m": used_radius_m,
        "radius_expanded": radius_expanded,
        "search_failures": search_failures,
    }
