"""장인영 담당: 정확한 목적지명 검색 -> 동명 확인용 후보.

출발 정류장 좌표를 기준으로 33km 반경까지 검색해 정확도순(searchtypCd=A) 결과를
그대로 반환한다. 반경 확장이나 재정렬은 하지 않는다(대분류 검색과 달리 정확한 이름
검색이므로 TMAP 자체 정확도 순서를 그대로 신뢰). 다만 이름이 정확히 일치하는 후보가
있으면 그것만 추려서(`narrow_exact_matches`) 반환한다 — 이 판단을 여기서 해야
`app/reservation/plan_route.py`(통합 흐름)와 `/api/destinations/name-search`(단독
엔드포인트) 양쪽이 항상 같은 결과를 보게 된다. 단일/복수 확인 필요 여부(사용자에게
고르게 할지 결정) 자체는 이 파일의 범위 밖이며, plan_route.py가 이어서 처리한다.
"""
from __future__ import annotations

from app.clients.tmap_client import Coordinate, MockTmapClient, POI, TmapClient
from app.geo import SearchKeywordType

EXACT_SEARCH_RADIUS_M = 33_000
EXACT_SEARCH_FETCH_COUNT = 5


def narrow_exact_matches(candidates: list[POI], place_name: str) -> list[POI]:
    """이름이 정확히 일치하는(공백·대소문자 무시) 후보가 있으면 그것만, 없으면
    원래 후보 전체를 반환한다."""
    normalized = place_name.replace(" ", "").lower()
    exact = [poi for poi in candidates if poi.name.replace(" ", "").lower() == normalized]
    return exact or candidates


async def search_by_name(
    client: TmapClient | MockTmapClient,
    place_name: str,
    departure_station_coord: Coordinate,
    *,
    radius_m: float = EXACT_SEARCH_RADIUS_M,
    fetch_count: int = EXACT_SEARCH_FETCH_COUNT,
) -> dict:
    """정확한 목적지명(예: "남현서울정형외과")으로 출발 정류장 좌표 기준 도착지 후보를 찾는다."""
    try:
        candidates = await client.search_pois(
            place_name, departure_station_coord, radius_m, fetch_count,
            keyword_type=SearchKeywordType.EXACT,
        )
    except Exception as exc:
        return {
            "status": "search_failed",
            "candidates": [],
            "reason": f"{type(exc).__name__}: {exc}",
        }

    if not candidates:
        return {
            "status": "no_candidates_found",
            "candidates": [],
            "reason": "출발 정류장 주변에서 일치하는 장소를 찾지 못했습니다.",
        }

    return {
        "status": "ok",
        "candidates": narrow_exact_matches(candidates, place_name),
        "reason": None,
    }
