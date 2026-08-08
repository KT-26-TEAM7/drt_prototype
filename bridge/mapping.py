"""분석 결과의 목적지 정보를 drt_service `/api/plan`의 `query`/`is_specific`으로 바꾼다.

drt_service의 목적지 검색은 두 갈래뿐이다.
- `is_specific=False`: 대분류 검색(app/destination/search_by_category.py). "정형외과"처럼
  종류만 주면 승차 정류장 주변에서 후보를 찾는다.
- `is_specific=True`: 정확명 검색(app/destination/search_by_name.py). "중앙도서관"처럼
  고유명사를 준다.

케어콜 분석기의 `search_mode`가 이 두 갈래 중 어디에 해당하는지를 여기서 정한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from bridge.contract import CareCallResult

# drt_analyzer.py의 destination_category -> 사람이 말로 하는 장소 이름.
# 음성으로 읽히므로 영어·한자를 넣지 않는다.
PLACE_WORD: dict[str, str] = {
    "medical_general": "병원", "medical_dental": "치과", "medical_orthopedics": "정형외과",
    "medical_dermatology": "피부과", "medical_internal": "내과", "medical_neurology": "신경과",
    "medical_ophthalmology": "안과", "medical_ent": "이비인후과",
    "medical_rehabilitation": "재활의학과", "pharmacy": "약국",
    "shopping_market": "시장", "shopping_mart": "마트", "shopping_convenience": "편의점",
    "public_community_center": "주민센터", "public_city_office": "구청", "public_bank": "은행",
    "welfare_center": "복지관", "senior_center": "경로당",
    "leisure_park": "공원", "leisure_culture_center": "문화센터", "leisure_library": "도서관",
    "exercise_gym": "헬스장", "exercise_swimming": "수영장", "exercise_sports_center": "체육관",
    "religious_church": "교회", "religious_catholic": "성당", "religious_temple": "절",
    "social_family_visit": "가족 집", "social_friend_visit": "친구 집",
    "unknown": "목적지",
    # v4.py(구버전 분석기)가 쓰던 넓은 카테고리도 받아 준다.
    "shopping": "시장", "public_office": "주민센터", "welfare": "복지관",
    "exercise": "운동 시설", "religious": "종교 시설", "social_visit": "방문 장소",
}

# drt_service PlanRequest.query의 max_length.
MAX_QUERY_LENGTH = 100


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """DRT 목적지 검색어."""

    query: str
    is_specific: bool
    source: str  # 어떤 근거로 만들었는지 (감사 로그용)


@dataclass(frozen=True, slots=True)
class QueryUnavailable:
    """검색어를 만들 수 없는 경우. 어르신께 되물어야 한다."""

    code: str
    spoken: str = ""


def place_word(category: str) -> str:
    return PLACE_WORD.get(category, "목적지")


def build_query(result: CareCallResult) -> QueryPlan | QueryUnavailable:
    """목적지 검색어를 만든다. 만들 수 없으면 되물을 질문과 함께 돌려준다."""
    # 1) 정확한 장소명이 있으면 무조건 그것이 우선이다.
    #    search_mode가 exact_place가 아니어도, 이름이 잡혔으면 정확명 검색이 더 정확하다.
    if result.specific_place:
        return QueryPlan(
            query=result.specific_place[:MAX_QUERY_LENGTH],
            is_specific=True,
            source="specific_place",
        )

    if result.search_mode == "exact_place":
        # 분석기는 정확명이 있다고 판단했는데 이름이 출력에 실려 오지 않은 경우다.
        # (drt_analyzer.py가 specific_place를 OUTPUT_KEYS에 넣지 않는 문제)
        return QueryUnavailable(
            "specific_place_missing",
            result.place_resolution_question or "어디로 가시는지 이름을 다시 한번 말씀해 주시겠어요?",
        )

    # 2) 가까운 곳 검색이면 대분류 검색어를 쓴다.
    if result.search_mode == "nearby_search":
        keyword = _first_keyword(result)
        if not keyword:
            return QueryUnavailable(
                "search_keyword_missing", "어디로 가시고 싶으신지 말씀해 주시겠어요?"
            )
        return QueryPlan(query=keyword[:MAX_QUERY_LENGTH], is_specific=False, source="nearby_search")

    # 3) 아직 "가까운 곳" 인지 "늘 가시던 곳"인지 안 정해졌거나, 주소를 직접 받아야 하는 경우.
    #    분석기가 만들어 둔 질문을 그대로 읽어 준다.
    question = result.place_resolution_question or result.next_question
    return QueryUnavailable(f"unresolved_search_mode:{result.search_mode or 'none'}", question)


def _first_keyword(result: CareCallResult) -> str:
    for source in (result.search_keywords, result.destination_candidates):
        for keyword in source:
            if keyword:
                return keyword
    word = place_word(result.destination_category)
    return "" if word == "목적지" else word
