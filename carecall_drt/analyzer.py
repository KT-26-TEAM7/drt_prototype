"""규칙 우선 DRT 대화 분석기.

핵심 원칙
1. 응급/거절/예약 동의/날짜·시간은 규칙을 우선한다.
2. Gemini는 규칙으로 모호한 의미를 보강할 때만 선택적으로 사용한다.
3. 질문은 규칙 템플릿으로 한 번에 하나만 만든다.
4. 다중 턴 상태를 유지하여 "내일" 같은 짧은 후속 답변도 앞 문맥과 합친다.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any, Callable, Protocol

from .config import Settings
from .schemas import DRTAnalysis, SemanticFrame, SessionState
from .taxonomy import BACKEND_QUERY, CATEGORIES, PLACE_WORD, ROUTE_BLOCKED_CATEGORIES


class SemanticEnricher(Protocol):
    def analyze(self, conversation: str) -> tuple[dict[str, Any] | None, float | None]: ...


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def strip_speaker(text: str) -> str:
    return re.sub(r"^\s*(어르신|사용자|user)\s*:\s*", "", str(text or ""), flags=re.I).strip()


def has_any(text: str, patterns: list[str] | tuple[str, ...]) -> bool:
    compact = normalize(text)
    return any(normalize(pattern) in compact for pattern in patterns)


def first_match(text: str, patterns: list[str] | tuple[str, ...]) -> str | None:
    compact = normalize(text)
    for pattern in patterns:
        if normalize(pattern) in compact:
            return pattern
    return None


def unique(items: list[str]) -> list[str]:
    output: list[str] = []
    for item in items:
        if isinstance(item, str):
            value = item.strip()
            if value and value not in output:
                output.append(value)
    return output


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "예", "네", "응"}:
            return True
        if lowered in {"false", "no", "0", "아니", "아니오"}:
            return False
    return default


def as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return unique([item for item in value if isinstance(item, str) and len(item.strip()) <= 80])


def pick(value: Any, allowed: tuple[str, ...] | set[str] | list[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


# ---------------------------------------------------------------------------
# 안전·의도·슬롯 규칙
# ---------------------------------------------------------------------------


def detect_emergency(text: str) -> bool:
    strong = has_any(
        text,
        [
            "숨이 차",
            "숨이 너무 차",
            "숨이 안 쉬",
            "숨이 잘 안 쉬",
            "호흡이 힘",
            "가슴이 답답",
            "가슴이 아프",
            "가슴 통증",
            "식은땀",
            "쓰러졌",
            "말이 안 나와",
            "말이 잘 안 나와",
            "한쪽 힘이 빠",
            "정신이 멍",
            "119",
            "응급실",
        ],
    )
    fall_negative = has_any(text, ["넘어지진 않았", "넘어지지는 않았", "넘어진 건 아니", "낙상은 아니"])
    severe_fall = (
        has_any(text, ["넘어졌", "넘어져서", "낙상"])
        and not fall_negative
        and has_any(text, ["못 일어나", "일어나기 힘", "일어나기가 너무 힘", "움직일 수가 없어", "움직일 수 없어"])
    )
    return strong or severe_fall


def extract_emergency_keywords(text: str) -> list[str]:
    groups = [
        ["숨이 너무 차", "숨이 차", "숨이 안 쉬", "호흡이 힘", "숨이 잘 안 쉬"],
        ["가슴이 답답", "가슴이 아프", "식은땀", "가슴 통증"],
        ["쓰러졌", "넘어졌", "넘어져서", "낙상"],
        ["못 일어나겠어", "못 일어나", "일어나기 힘", "일어나기가 너무 힘"],
        ["움직일 수가 없어", "움직일 수 없어"],
        ["말이 안 나와", "말이 잘 안 나와"],
        ["한쪽 힘이 빠", "정신이 멍"],
        ["119", "응급실"],
    ]
    return unique([matched for group in groups if (matched := first_match(text, group))])


def detect_not_needed(text: str) -> tuple[bool, bool]:
    refused = has_any(
        text,
        [
            "차는 안 불러도 돼",
            "차 안 불러도 돼",
            "예약 안 해도 돼",
            "예약은 안 해줘도 돼",
            "차량 예약은 안 해줘도 돼",
            "차 부르지 마",
            "아들이 데려다준대",
            "딸이 데려다준대",
            "가족이 데려다준대",
            "택시 타고 갈게",
            "택시 타고 가",
        ],
    )
    not_needed = has_any(
        text,
        [
            "집에서 쉴래",
            "집에 있을래",
            "안 나갈래",
            "오늘은 안 가",
            "안 가도 될 것 같아",
            "취소할래",
            "그냥 집에 있을",
        ],
    )
    return refused or not_needed, refused


def detect_reservation_request(text: str) -> bool:
    return has_any(
        text,
        [
            "차 좀 불러줘",
            "차 불러줘",
            "차량 예약해줘",
            "이동 차량 예약해줘",
            "이동차량 예약해줘",
            "DRT 예약해줘",
            "디알티 예약해줘",
            "버스 불러줘",
            "버스 예약해줘",
            "차량 호출해줘",
        ],
    )


def detect_visit_intent(text: str) -> bool:
    if has_any(text, ["가야 하나 싶", "받아야 하나 싶", "가야 할까", "받아야 할까"]):
        return False
    return has_any(
        text,
        [
            "가야",
            "갈 거야",
            "갈거야",
            "가려고",
            "가고 싶",
            "나가려고",
            "방문",
            "진료",
            "치료",
            "받으러",
            "사러",
            "장보러",
            "친구 만나러",
            "예배",
            "미사",
            "법회",
            "민원",
            "모임",
            "다녀오고 싶",
            "다녀오려고",
            "이동 차량",
            "차 좀 불러",
        ],
    )


def detect_mobility_difficulty(text: str, reservation_request: bool = False) -> bool:
    if reservation_request:
        return True
    return has_any(
        text,
        [
            "버스 타기 힘",
            "버스 타기가 힘",
            "버스 타기 어려",
            "걷기 힘",
            "걷기가 힘",
            "걷기 어려",
            "혼자 가기 힘",
            "혼자 가기가 힘",
            "혼자 가기 어려",
            "이동이 힘",
            "이동하기 힘",
            "차가 없어",
            "멀어서 못 가",
        ],
    )


def extract_date(text: str) -> str | None:
    return first_match(
        text,
        [
            "오늘",
            "내일",
            "모레",
            "이번 주말",
            "이번주말",
            "주말",
            "월요일",
            "화요일",
            "수요일",
            "목요일",
            "금요일",
            "토요일",
            "일요일",
        ],
    )


def extract_time(text: str) -> str | None:
    match = re.search(r"(오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분|\s*반)?", text)
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip()
    return first_match(text, ["이른 아침", "아침", "오전", "점심때", "점심", "오후", "저녁", "밤"])


def extract_pickup(text: str) -> str | None:
    return first_match(
        text,
        ["우리 집 앞", "우리집 앞", "집 앞", "집에서", "우리 집", "우리집", "자택", "아파트 앞", "현 위치", "현재 위치"],
    )


def detect_place_preference(text: str) -> str:
    if has_any(text, ["가까운", "근처", "추천", "아무 데나", "아무데나"]):
        return "nearby"
    if has_any(text, ["평소 다니는", "자주 가는", "단골", "항상 가던", "다니던"]):
        return "frequent"
    return "unknown"


def is_affirmative(text: str) -> bool:
    """예/아니오를 묻는 질문(특히 "이 경로로 예약할까요?")에 대한 답을 판정한다.

    실제 통화(2026-08-12)에서 "어 불러줘"/"응 불러줘"/"불러줘"라고 반복 답해도
    예약이 진행되지 않고 같은 확인 질문만 되풀이되는 문제가 확인됐다 — "불러줘"가
    긍정 목록에 없어 감지 못하고 있었다(정작 처음 차량을 요청할 때 쓰는 말인
    "차 좀 불러줘"와 같은 동사인데도 확인 답변으로는 인식 못 함). "어 불러줘"처럼
    "불러"가 맨 앞이 아니라 필러 뒤에 오는 경우까지 잡아야 해서, 이 단어만은
    문장 앞머리가 아니라 어디에 있든 긍정으로 본다("불러"는 이 도메인에서 차량
    호출 의미로만 쓰여 다른 뜻과 헷갈릴 위험이 낮다).
    """
    compact = normalize(strip_speaker(text))
    affirmative = {
        "응",
        "네",
        "예",
        "그래",
        "좋아",
        "해주세요",
        "해줘",
        "그래줘",
        "그렇게해줘",
        "예약해줘",
        "맞아",
    }
    # "안 불러도 돼"/"못 불러"처럼 부정어와 결합되면 "불러"가 들어 있어도 긍정이
    # 아니다 — is_negative()가 이미 이런 문장을 따로 잡아 준다.
    calls_it = "불러" in compact and not has_any(compact, ["안불러", "못불러"])
    return (
        compact in affirmative
        or compact.startswith(("응", "네", "예", "그래", "좋아"))
        or calls_it
    )


def is_negative(text: str) -> bool:
    compact = normalize(strip_speaker(text))
    return compact in {"아니", "아니요", "아니오", "싫어", "괜찮아", "안할래", "필요없어"} or compact.startswith(
        ("아니", "싫어", "안할")
    )


# ---------------------------------------------------------------------------
# 목적지 규칙
# ---------------------------------------------------------------------------


_SPECIFIC_SUFFIXES = (
    "정형외과의원",
    "재활의학과의원",
    "이비인후과의원",
    "행정복지센터",
    "종합복지관",
    "정형외과",
    "재활의학과",
    "이비인후과",
    "피부과",
    "치과",
    "내과",
    "안과",
    "신경과",
    "병원",
    "의원",
    "약국",
    "전통시장",
    "시장",
    "마트",
    "편의점",
    "주민센터",
    "구청",
    "시청",
    "군청",
    "은행",
    "복지관",
    "경로당",
    "도서관",
    "공원",
    "교회",
    "성당",
    "사찰",
)

_GENERIC_PLACES = {
    "치과",
    "정형외과",
    "피부과",
    "내과",
    "안과",
    "이비인후과",
    "재활의학과",
    "병원",
    "의원",
    "약국",
    "시장",
    "마트",
    "편의점",
    "주민센터",
    "행정복지센터",
    "구청",
    "시청",
    "군청",
    "은행",
    "복지관",
    "경로당",
    "도서관",
    "공원",
    "교회",
    "성당",
    "절",
}

_LEADING_NOISE = (
    "가까운",
    "근처의",
    "근처",
    "평소다니는",
    "자주가는",
    "오늘",
    "내일",
    "모레",
    "어제",
    "저기",
    "그",
    "우리",
)


def extract_specific_place(text: str) -> str | None:
    source = strip_speaker(text)
    suffix_pattern = "|".join(re.escape(item) for item in _SPECIFIC_SUFFIXES)
    # 한글/영문/숫자로 이루어진 실제 장소명만 잡고, 조사와 동사는 제외한다.
    matches = re.findall(rf"([가-힣A-Za-z0-9·&]{{2,24}}(?:{suffix_pattern}))", source)
    for raw in matches:
        candidate = normalize(raw)
        changed = True
        while changed:
            changed = False
            for prefix in _LEADING_NOISE:
                normalized_prefix = normalize(prefix)
                if candidate.startswith(normalized_prefix) and len(candidate) > len(normalized_prefix) + 1:
                    candidate = candidate[len(normalized_prefix) :]
                    changed = True
        if candidate not in _GENERIC_PLACES and len(candidate) >= 3:
            return candidate
    return None


def category_from_specific_place(place: str) -> str:
    compact = normalize(place)
    if "치과" in compact:
        return "medical_dental"
    if "정형외과" in compact:
        return "medical_orthopedics"
    if "피부과" in compact:
        return "medical_dermatology"
    if "재활의학과" in compact:
        return "medical_rehabilitation"
    if "이비인후과" in compact:
        return "medical_ent"
    if compact.endswith("내과"):
        return "medical_internal"
    if compact.endswith("안과"):
        return "medical_ophthalmology"
    if compact.endswith("신경과"):
        return "medical_neurology"
    if compact.endswith(("병원", "의원")):
        return "medical_general"
    if compact.endswith("약국"):
        return "pharmacy"
    if compact.endswith(("전통시장", "시장")):
        return "shopping_market"
    if compact.endswith("마트"):
        return "shopping_mart"
    if compact.endswith("편의점"):
        return "shopping_convenience"
    if compact.endswith(("주민센터", "행정복지센터")):
        return "public_community_center"
    if compact.endswith(("구청", "시청", "군청")):
        return "public_city_office"
    if compact.endswith("은행"):
        return "public_bank"
    if compact.endswith("복지관"):
        return "welfare_center"
    if compact.endswith("경로당"):
        return "senior_center"
    if compact.endswith("도서관"):
        return "leisure_library"
    if compact.endswith("공원"):
        return "leisure_park"
    if compact.endswith("교회"):
        return "religious_church"
    if compact.endswith("성당"):
        return "religious_catholic"
    if compact.endswith("사찰"):
        return "religious_temple"
    return "unknown"


def infer_destination(text: str) -> tuple[str, list[str], str | None]:
    specific = extract_specific_place(text)
    if specific:
        return category_from_specific_place(specific), [specific], specific

    # 단일 글자(예: 목)는 목요일 같은 표현에 오탐될 수 있으므로 문맥 표현만 사용한다.
    rules: list[tuple[str, list[str], list[str]]] = [
        ("medical_dental", ["치과", "치아", "이가 아", "잇몸", "치통"], ["치과"]),
        ("medical_dermatology", ["피부과", "피부가", "피부가 가려", "상처가", "두드러기"], ["피부과"]),
        ("medical_orthopedics", ["정형외과", "무릎이 아", "허리가 아", "관절", "근육통", "뼈가", "골절"], ["정형외과"]),
        ("medical_internal", ["내과", "복통", "소화가", "기침이", "열이", "배가 아", "속이 아"], ["내과"]),
        ("medical_ophthalmology", ["안과", "눈이 침침", "눈이 아", "시야가", "잘 안 보여"], ["안과"]),
        ("medical_ent", ["이비인후과", "귀가", "귀가 잘", "목이 아", "코가 막", "콧물"], ["이비인후과"]),
        ("medical_rehabilitation", ["재활의학과", "재활", "물리치료"], ["재활의학과"]),
        ("medical_neurology", ["신경과", "손발이 저", "떨림"], ["신경과"]),
        ("pharmacy", ["약국", "약 받", "처방전"], ["약국"]),
        ("shopping_market", ["시장", "재래시장", "전통시장"], ["시장"]),
        ("shopping_convenience", ["편의점"], ["편의점"]),
        ("shopping_mart", ["마트", "장보러", "장 보러", "생필품 사러"], ["마트"]),
        ("public_city_office", ["구청", "시청", "군청"], ["구청"]),
        ("public_community_center", ["주민센터", "행정복지센터", "등본 떼"], ["주민센터"]),
        ("public_bank", ["은행", "통장 정리", "입금하러", "출금하러"], ["은행"]),
        ("welfare_center", ["복지관"], ["복지관"]),
        ("senior_center", ["경로당", "노인정"], ["경로당"]),
        ("leisure_library", ["도서관", "책 빌리"], ["도서관"]),
        ("leisure_park", ["공원", "산책하러"], ["공원"]),
        ("religious_church", ["교회", "예배"], ["교회"]),
        ("religious_catholic", ["성당", "미사"], ["성당"]),
        ("religious_temple", ["절에", "절로", "법회", "사찰"], ["절"]),
        (
            "social_family_visit",
            ["아들 집", "딸 집", "손자 집", "손녀 집", "아들네", "딸네", "손자네", "손녀네", "가족 집", "가족 만나"],
            ["가족 방문 장소"],
        ),
        ("social_friend_visit", ["친구 만나러", "지인 만나러", "친구 집", "모임에"], ["친구 방문 장소"]),
        ("medical_general", ["병원", "진료받", "검진", "건강검진"], ["병원"]),
    ]

    for category, keywords, candidates in rules:
        if has_any(text, keywords):
            return category, candidates, None
    return "unknown", [], None


# ---------------------------------------------------------------------------
# Gemini 선택·병합
# ---------------------------------------------------------------------------


def make_rule_semantic(text: str) -> SemanticFrame:
    category, candidates, specific_place = infer_destination(text)
    reservation_request = detect_reservation_request(text)
    not_needed, refused = detect_not_needed(text)
    mobility_difficulty = detect_mobility_difficulty(text, reservation_request)
    # 목적지와 이동 어려움이 동시에 명시되면 방문 필요성이 있는 것으로 본다.
    # 예: "버스 타기가 힘들어서 병원 가기 어려워". Gemini가 꺼져 있어도
    # DRT 확인 단계로 자연스럽게 이어지도록 하는 규칙 보완이다.
    visit_intent = (
        detect_visit_intent(text)
        or reservation_request
        or (category != "unknown" and mobility_difficulty)
    )

    return SemanticFrame(
        visit_intent=visit_intent,
        outing_status=(
            "refused"
            if refused
            else "not_needed"
            if not_needed
            else "intended"
            if visit_intent
            else "unknown"
        ),
        reservation_request=reservation_request,
        reservation_consent=("confirmed" if reservation_request else "refused" if refused else "not_confirmed"),
        destination_category=category,
        destination_candidates=candidates,
        specific_place=specific_place or "",
        place_preference="exact" if specific_place else detect_place_preference(text),
        mobility_difficulty=mobility_difficulty,
        emergency_risk=detect_emergency(text),
        extracted_keywords=[],
    )


def should_call_gemini(text: str, rule: SemanticFrame, policy: str = "ambiguous_only") -> bool:
    if policy == "off" or rule.emergency_risk:
        return False
    not_needed, _ = detect_not_needed(text)
    if not_needed:
        return False

    if policy == "candidate":
        return rule.reservation_request or (
            rule.destination_category != "unknown" and (rule.visit_intent or rule.mobility_difficulty)
        )

    # ambiguous_only: 규칙만으로 핵심 슬롯이 명확하면 호출하지 않는다.
    if not (rule.reservation_request or rule.visit_intent or rule.mobility_difficulty):
        return False
    if rule.destination_category == "unknown":
        return True
    if rule.destination_category == "medical_general" and not rule.specific_place:
        return True
    # 직접 장소를 말한 것처럼 보이지만 정규식이 놓쳤을 가능성이 있는 긴 고유명사 발화.
    if rule.place_preference == "exact" and not rule.specific_place:
        return True
    return False


def merge_semantic(rule: SemanticFrame, llm: dict[str, Any] | None, text: str) -> SemanticFrame:
    if not isinstance(llm, dict):
        return rule

    merged = replace(rule)
    merged.destination_candidates = list(rule.destination_candidates)
    merged.extracted_keywords = list(rule.extracted_keywords)

    merged.visit_intent = rule.visit_intent or as_bool(llm.get("visit_intent"), False)

    llm_preference = pick(llm.get("place_preference"), {"unknown", "nearby", "frequent", "exact"}, "unknown")
    if rule.place_preference == "unknown" and llm_preference != "unknown":
        merged.place_preference = llm_preference

    llm_specific = llm.get("specific_place") if isinstance(llm.get("specific_place"), str) else ""
    # 모델이 지어낸 장소를 막기 위해 실제 원문에 포함된 경우만 사용한다.
    if not rule.specific_place and llm_specific and normalize(llm_specific) in normalize(text):
        merged.specific_place = llm_specific.strip()
        merged.place_preference = "exact"
        inferred = category_from_specific_place(merged.specific_place)
        if merged.destination_category == "unknown" and inferred != "unknown":
            merged.destination_category = inferred
            merged.destination_candidates = [merged.specific_place]

    llm_category = pick(llm.get("destination_category"), CATEGORIES, "unknown")
    if rule.destination_category == "unknown" and llm_category != "unknown":
        merged.destination_category = llm_category
        merged.destination_candidates = as_list(llm.get("destination_candidates"))

    merged.extracted_keywords = unique(as_list(llm.get("extracted_keywords")) + rule.extracted_keywords)
    return merged


# ---------------------------------------------------------------------------
# 다중 턴 문맥 처리
# ---------------------------------------------------------------------------


def _clean_exact_answer(text: str) -> str:
    value = strip_speaker(text)
    value = re.sub(r"(으로|로|에)?\s*(가고 싶어|갈래|가야 해|가줘|예약해줘|차 불러줘).*$", "", value).strip()
    return value[:100]


def apply_contextual_answer(text: str, target_slot: str | None, frame: SemanticFrame) -> SemanticFrame:
    if not target_slot:
        return frame

    result = replace(frame)
    result.destination_candidates = list(frame.destination_candidates)
    result.extracted_keywords = list(frame.extracted_keywords)

    if target_slot == "reservation_consent":
        if is_affirmative(text):
            result.visit_intent = True
            result.outing_status = "intended"
            result.reservation_consent = "confirmed"
        elif is_negative(text):
            result.outing_status = "refused"
            result.reservation_consent = "refused"
        return result

    if target_slot == "visit_intent":
        if is_affirmative(text):
            result.visit_intent = True
            result.outing_status = "intended"
        elif is_negative(text):
            result.outing_status = "not_needed"
        return result

    if target_slot == "place_resolution_method":
        preference = detect_place_preference(text)
        if preference != "unknown":
            result.place_preference = preference
        elif is_affirmative(text) and has_any(text, ["가까", "근처"]):
            result.place_preference = "nearby"
        return result

    if target_slot == "medical_department":
        category, candidates, specific = infer_destination(text)
        if category not in {"unknown", "medical_general"}:
            result.destination_category = category
            result.destination_candidates = candidates
            result.specific_place = specific or result.specific_place
            if specific:
                result.place_preference = "exact"
        return result

    if target_slot == "destination_category":
        category, candidates, specific = infer_destination(text)
        if category != "unknown":
            result.destination_category = category
            result.destination_candidates = candidates
            result.specific_place = specific or ""
            if specific:
                result.place_preference = "exact"
        return result

    if target_slot == "exact_destination":
        specific = extract_specific_place(text) or _clean_exact_answer(text)
        if specific and len(normalize(specific)) >= 2 and not is_affirmative(text) and not is_negative(text):
            result.specific_place = specific
            result.place_preference = "exact"
            category = category_from_specific_place(specific)
            if result.destination_category == "unknown" and category != "unknown":
                result.destination_category = category
            result.destination_candidates = [specific]
        return result

    return result


def _overlay_frames(base: SemanticFrame, extra: SemanticFrame) -> SemanticFrame:
    """현재 턴의 명시적 정보(extra)를 문맥 프레임(base)에 합친다."""
    merged = replace(base)
    merged.destination_candidates = list(base.destination_candidates)
    merged.extracted_keywords = list(base.extracted_keywords)

    if extra.visit_intent:
        merged.visit_intent = True
    if extra.outing_status != "unknown":
        merged.outing_status = extra.outing_status
    if extra.reservation_request:
        merged.reservation_request = True
    if extra.reservation_consent != "not_confirmed":
        merged.reservation_consent = extra.reservation_consent
    if extra.destination_category != "unknown":
        merged.destination_category = extra.destination_category
        merged.destination_candidates = list(extra.destination_candidates)
    if extra.specific_place:
        merged.specific_place = extra.specific_place
    if extra.place_preference != "unknown":
        merged.place_preference = extra.place_preference
    merged.mobility_difficulty = base.mobility_difficulty or extra.mobility_difficulty
    merged.emergency_risk = base.emergency_risk or extra.emergency_risk
    merged.extracted_keywords = unique(base.extracted_keywords + extra.extracted_keywords)
    return merged


def _session_frame(state: SessionState) -> SemanticFrame:
    return SemanticFrame(
        visit_intent=state.visit_intent,
        outing_status=state.outing_status,
        reservation_request=state.reservation_consent == "confirmed",
        reservation_consent=state.reservation_consent,
        destination_category=state.destination_category,
        destination_candidates=list(state.destination_candidates),
        specific_place=state.specific_place,
        place_preference=state.place_preference,
        mobility_difficulty=state.mobility_difficulty,
        emergency_risk=False,  # 응급은 매 턴 새로 판단한다.
        extracted_keywords=[],
    )


def update_session(state: SessionState, semantic: SemanticFrame, date: str | None, time_: str | None, pickup: str | None) -> None:
    state.visit_intent = semantic.visit_intent or state.visit_intent
    if semantic.outing_status != "unknown":
        state.outing_status = semantic.outing_status
    if semantic.reservation_consent != "not_confirmed":
        state.reservation_consent = semantic.reservation_consent
    if semantic.destination_category != "unknown":
        state.destination_category = semantic.destination_category
        state.destination_candidates = list(semantic.destination_candidates)
    if semantic.specific_place:
        state.specific_place = semantic.specific_place
    if semantic.place_preference != "unknown":
        state.place_preference = semantic.place_preference
    state.mobility_difficulty = state.mobility_difficulty or semantic.mobility_difficulty
    state.emergency_risk = semantic.emergency_risk
    if date:
        state.date = date
    if time_:
        state.time = time_
    if pickup:
        state.pickup_location = pickup


# ---------------------------------------------------------------------------
# 최종 stage, missing slot, 질문
# ---------------------------------------------------------------------------


def decide_stage(semantic: SemanticFrame) -> tuple[str, str]:
    if semantic.emergency_risk:
        return "emergency", "emergency"
    if semantic.outing_status in {"not_needed", "refused"} or semantic.reservation_consent == "refused":
        return "not_needed", "not_needed"
    if semantic.reservation_request or semantic.reservation_consent == "confirmed":
        return "reservation_info_collection", "needed"
    if semantic.visit_intent:
        return "reservation_confirm", "possible"
    return "need_detection", "unclear"


def build_missing(
    stage: str,
    semantic: SemanticFrame,
    date: str | None,
    time_: str | None,
    pickup: str | None,
) -> list[str]:
    if stage in {"emergency", "not_needed"}:
        return []
    if stage == "need_detection":
        return ["visit_intent"]
    if stage == "reservation_confirm":
        if semantic.destination_category == "unknown":
            return ["destination_category"]
        return ["reservation_consent"]

    missing: list[str] = []
    if semantic.destination_category == "unknown":
        missing.append("destination_category")
    else:
        if semantic.destination_category == "medical_general" and not semantic.specific_place:
            missing.append("medical_department")

        if not semantic.specific_place:
            if semantic.destination_category.startswith("social_"):
                missing.append("exact_destination")
            elif semantic.place_preference == "unknown":
                missing.append("place_resolution_method")
            elif semantic.place_preference in {"frequent", "exact"}:
                missing.append("exact_destination")

    if not date:
        missing.append("date")
    if not time_:
        missing.append("time")
    if not pickup:
        missing.append("pickup_location")
    return unique(missing)


TARGET_SLOT_ORDER = (
    "visit_intent",
    "destination_category",
    "reservation_consent",
    "medical_department",
    "place_resolution_method",
    "exact_destination",
    "date",
    "time",
    "pickup_location",
)


def pick_target_slot(stage: str, missing: list[str]) -> str | None:
    if stage in {"emergency", "not_needed"}:
        return None
    return next((slot for slot in TARGET_SLOT_ORDER if slot in missing), None)


def _has_final_consonant(word: str) -> bool:
    if not word:
        return False
    code = ord(word[-1])
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def _subject_particle(word: str) -> str:
    return "이" if _has_final_consonant(word) else "가"


def _direction_particle(word: str) -> str:
    if not word:
        return "으로"
    code = ord(word[-1])
    if not (0xAC00 <= code <= 0xD7A3):
        return "으로"
    jong = (code - 0xAC00) % 28
    return "로" if jong in {0, 8} else "으로"  # 받침 없음 또는 ㄹ 받침


def build_next_question(stage: str, semantic: SemanticFrame, target_slot: str | None) -> str:
    place = PLACE_WORD.get(semantic.destination_category, "목적지")
    if stage == "emergency":
        return "지금 바로 보호자나 119에 연결해드릴까요?"
    if stage == "not_needed":
        return ""
    if target_slot == "visit_intent":
        return "오늘 어디 다녀오실 계획이 있으실까요?"
    if target_slot == "destination_category":
        return "어디에 다녀오실 계획이신지 여쭤봐도 될까요?"
    if target_slot == "reservation_consent":
        return f"{place}에 가시는 이동 차량 예약을 도와드릴까요?"
    if target_slot == "medical_department":
        return "어디가 불편해서 병원에 가시려는 걸까요?"
    if target_slot == "place_resolution_method":
        return (
            f"평소 자주 가시는 {place}{_subject_particle(place)} 있으실까요? "
            f"아니면 가까운 {place}{_direction_particle(place)} 안내해드릴까요?"
        )
    if target_slot == "exact_destination":
        return "방문하실 곳의 정확한 장소명이나 주소를 알려주실 수 있을까요?"
    if target_slot == "date":
        return "가실 날짜를 알려주실 수 있을까요?"
    if target_slot == "time":
        return "가실 시간을 알려주실 수 있을까요?"
    if target_slot == "pickup_location":
        return "출발하실 위치를 알려주실 수 있을까요?"
    return "예약 정보를 모두 확인했습니다."


def is_non_drt_casual(stage: str, call_flag: bool, semantic: SemanticFrame) -> bool:
    """제공된 원본 코드에서 호출되지만 누락되어 있던 함수를 보완한다."""
    return (
        stage == "need_detection"
        and not call_flag
        and not semantic.visit_intent
        and semantic.destination_category == "unknown"
        and not semantic.mobility_difficulty
        and not semantic.emergency_risk
        and semantic.outing_status == "unknown"
    )


def build_reason(stage: str, gemini_used: bool) -> str:
    mode = "Gemini와 규칙 기반 분석" if gemini_used else "규칙 기반 분석"
    if stage == "emergency":
        return f"{mode} 결과, 응급 가능성이 있어 DRT 예약보다 보호자 또는 119 연결이 우선입니다."
    if stage == "not_needed":
        return f"{mode} 결과, DRT 예약이 필요 없거나 사용자가 차량 호출을 원하지 않는 것으로 판단했습니다."
    if stage == "reservation_info_collection":
        return f"{mode} 결과, DRT 호출 의향이 확인되어 예약 정보 수집 단계로 판단했습니다."
    if stage == "reservation_confirm":
        return f"{mode} 결과, 외출 의향은 있으나 DRT 예약 동의가 아직 확인되지 않았습니다."
    return f"{mode} 결과, DRT 호출 의향이 명확하지 않아 추가 확인이 필요합니다."


def route_metadata(state: SessionState, semantic: SemanticFrame) -> tuple[bool, bool, str | None, bool]:
    is_specific = bool(semantic.specific_place)
    query = semantic.specific_place or BACKEND_QUERY.get(semantic.destination_category)

    destination_ready = bool(query) and semantic.destination_category not in ROUTE_BLOCKED_CATEGORIES
    if semantic.destination_category == "medical_general" and not is_specific:
        destination_ready = False
    if not is_specific and semantic.place_preference not in {"nearby"}:
        destination_ready = False

    consent_ready = semantic.reservation_consent == "confirmed" or semantic.reservation_request
    ready_for_plan = bool(destination_ready and consent_ready and state.location is not None)
    ready_for_reservation = ready_for_plan and bool(state.date and state.time and state.pickup_location)
    return ready_for_plan, ready_for_reservation, query, is_specific


class DRTAnalyzer:
    def __init__(self, settings: Settings | None = None, semantic_enricher: SemanticEnricher | None = None):
        self.settings = settings or Settings()
        self.settings.validate()
        self.semantic_enricher = semantic_enricher

    def precheck(self, text: str, state: SessionState | None = None) -> tuple[SemanticFrame, bool]:
        state = state or SessionState()
        current = make_rule_semantic(text)
        contextual = apply_contextual_answer(text, state.last_target_slot, current)
        combined = _overlay_frames(_session_frame(state), contextual)
        call_flag = should_call_gemini(text, combined, self.settings.gemini_policy)
        return combined, call_flag

    def analyze_turn(
        self,
        text: str,
        state: SessionState | None = None,
        *,
        llm_semantic: dict[str, Any] | None = None,
        allow_internal_gemini: bool = True,
    ) -> DRTAnalysis:
        state = state or SessionState()
        started = time.perf_counter()

        current = make_rule_semantic(text)
        current = apply_contextual_answer(text, state.last_target_slot, current)
        semantic = _overlay_frames(_session_frame(state), current)
        call_flag = should_call_gemini(text, semantic, self.settings.gemini_policy)

        gemini_latency_ms: float | None = None
        payload = llm_semantic
        if payload is None and call_flag and allow_internal_gemini and self.semantic_enricher is not None:
            payload, gemini_latency_ms = self.semantic_enricher.analyze(text)
        gemini_used = isinstance(payload, dict)
        semantic = merge_semantic(semantic, payload, text)

        date = extract_date(text) or state.date
        time_ = extract_time(text) or state.time
        # extract_pickup()은 "집 앞"류 고정 문구만 인식한다. 정류장·역 이름처럼
        # 자유롭게 말씀하신 장소는 못 잡는데, exact_destination과 달리 문맥 인지
        # 자유 응답 처리가 없어서 "출발하실 위치를 알려주실 수 있을까요?"에
        # "사당역"이라고 답해도 계속 같은 질문을 반복하는 무한 루프가 생겼다
        # (2026-08-12 실제 통화에서 재현·확인). exact_destination과 같은 방식으로
        # 방금 그 슬롯을 물어본 경우에만 원문을 그대로 픽업 위치로 받는다.
        pickup_from_turn = extract_pickup(text)
        if (
            pickup_from_turn is None
            and state.last_target_slot == "pickup_location"
            and not is_affirmative(text)
            and not is_negative(text)
        ):
            candidate = _clean_exact_answer(text)
            if candidate and len(normalize(candidate)) >= 2:
                pickup_from_turn = candidate
        pickup = pickup_from_turn or state.pickup_location

        update_session(state, semantic, extract_date(text), extract_time(text), pickup_from_turn)
        # update_session 후 누적 상태를 다시 semantic으로 반영한다.
        semantic = _overlay_frames(_session_frame(state), semantic)
        stage, drt_status = decide_stage(semantic)
        missing = build_missing(stage, semantic, date, time_, pickup)
        target_slot = pick_target_slot(stage, missing)
        next_question = build_next_question(stage, semantic, target_slot)

        if is_non_drt_casual(stage, call_flag, semantic):
            missing = []
            target_slot = None
            next_question = ""

        ready_for_plan, ready_for_reservation, route_query, is_specific = route_metadata(state, semantic)
        emergency_keywords = extract_emergency_keywords(text) if semantic.emergency_risk else []
        keywords = unique(
            semantic.extracted_keywords
            + emergency_keywords
            + semantic.destination_candidates
            + [value for value in [date, time_, pickup, semantic.specific_place] if value]
        )

        analysis = DRTAnalysis(
            dialogue_stage=stage,
            drt_status=drt_status,
            destination_category=semantic.destination_category,
            destination_candidates=list(semantic.destination_candidates),
            visit_intent=semantic.visit_intent,
            outing_status=semantic.outing_status,
            reservation_consent=semantic.reservation_consent,
            mobility_difficulty=semantic.mobility_difficulty,
            emergency_risk=semantic.emergency_risk,
            should_call_gemini=call_flag,
            gemini_used=gemini_used,
            specific_place=semantic.specific_place,
            place_preference=semantic.place_preference,
            missing_slots=missing,
            target_slot=target_slot,
            next_question=next_question,
            reason=build_reason(stage, gemini_used),
            extracted_keywords=keywords,
            date=date,
            time=time_,
            pickup_location=pickup,
            ready_for_plan=ready_for_plan,
            ready_for_reservation=ready_for_reservation,
            route_query=route_query,
            is_specific=is_specific,
            rule_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            gemini_latency_ms=gemini_latency_ms,
        )
        state.last_target_slot = target_slot
        state.last_analysis = analysis
        return analysis
