"""DRT 목적지 분류 체계와 화면 표시용 문구.

이 값들은 이재령 코드의 category 체계를 그대로 유지하면서,
DRT 백엔드(TMAP 키워드 검색)가 사용할 한국어 검색어를 명시적으로 매핑한다.
"""

from __future__ import annotations

CATEGORIES: tuple[str, ...] = (
    "medical_general",
    "medical_dental",
    "medical_orthopedics",
    "medical_dermatology",
    "medical_internal",
    "medical_neurology",
    "medical_ophthalmology",
    "medical_ent",
    "medical_rehabilitation",
    "pharmacy",
    "shopping_market",
    "shopping_mart",
    "shopping_convenience",
    "public_community_center",
    "public_city_office",
    "public_bank",
    "welfare_center",
    "senior_center",
    "leisure_park",
    "leisure_library",
    "religious_church",
    "religious_catholic",
    "religious_temple",
    "social_family_visit",
    "social_friend_visit",
    "unknown",
)

PLACE_WORD: dict[str, str] = {
    "medical_general": "병원",
    "medical_dental": "치과",
    "medical_orthopedics": "정형외과",
    "medical_dermatology": "피부과",
    "medical_internal": "내과",
    "medical_neurology": "신경과",
    "medical_ophthalmology": "안과",
    "medical_ent": "이비인후과",
    "medical_rehabilitation": "재활의학과",
    "pharmacy": "약국",
    "shopping_market": "시장",
    "shopping_mart": "마트",
    "shopping_convenience": "편의점",
    "public_community_center": "주민센터",
    "public_city_office": "구청이나 시청",
    "public_bank": "은행",
    "welfare_center": "복지관",
    "senior_center": "경로당",
    "leisure_park": "공원",
    "leisure_library": "도서관",
    "religious_church": "교회",
    "religious_catholic": "성당",
    "religious_temple": "절",
    "social_family_visit": "가족 방문 장소",
    "social_friend_visit": "친구 방문 장소",
    "unknown": "목적지",
}

# TMAP /api/plan의 query에 넘기는 기본 검색어.
BACKEND_QUERY: dict[str, str] = {
    key: value for key, value in PLACE_WORD.items() if key != "unknown"
}

# 일반 병원은 세부 진료과 확인이 필요하므로 바로 검색하지 않는다.
ROUTE_BLOCKED_CATEGORIES = {"unknown", "social_family_visit", "social_friend_visit"}

OUTPUT_KEYS: tuple[str, ...] = (
    "dialogue_stage",
    "drt_status",
    "destination_category",
    "destination_candidates",
    "visit_intent",
    "outing_status",
    "reservation_consent",
    "mobility_difficulty",
    "emergency_risk",
    "should_call_gemini",
    "gemini_used",
    "specific_place",
    "place_preference",
    "missing_slots",
    "target_slot",
    "next_question",
    "reason",
    "extracted_keywords",
    "date",
    "time",
    "pickup_location",
    "ready_for_plan",
    "ready_for_reservation",
    "route_query",
    "is_specific",
)
