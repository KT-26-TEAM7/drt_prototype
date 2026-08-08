# -*- coding: utf-8 -*-
"""
drt_analyzer.py
Gemini semantic analysis + rule-based DRT flow controller

핵심 구조:
1) Gemini: 발화 의미 분석
2) Rules: 날짜/시간/장소/주소/missing_slots/next_question 최종 결정

케어콜 대화(chat_demo.py, gemini_chat_demo.py)에서 매 턴마다
analyze_conversation()을 호출해 DRT 상태를 함께 뽑아내는 용도로도 쓰인다.
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()


# =============================
# Settings
# =============================

USE_GEMINI = True  # 한도 아끼려면 False, Gemini 최종 확인 때만 True
SHOW_RAW_GEMINI = False
MODEL_NAME = "gemini-3.6-flash"
GEMINI_TEMP_DISABLED = False #한 번 Gemini quota 초과가 발생하면, 같은 실행 안에서는 Gemini를 더 이상 부르지 않게 함

# Free tier 요청 제한 방지용. 빠르게 테스트하려면 0으로 바꿔도 됨.
REQUEST_DELAY_SEC = 25.0

SELECTED_TEST_NAME: Optional[str] = None

TEST_CASES = [
    ("new_01_bank_confirm_priority", "어르신: 은행에 통장 정리하러 가야 해."),
    ("new_02_friend_confirm_priority", "어르신: 친구 만나러 가고 싶은데 혼자 가기가 힘들어."),
    ("new_03_family_visit", "어르신: 딸 집에 가고 싶은데 혼자 가기가 힘들어."),
    ("new_04_nearby_market", "어르신: 오늘 오후 2시에 가까운 시장으로 차 좀 불러줘."),
    ("new_05_frequent_senior_center", "어르신: 평소 다니는 경로당에 내일 오전 10시에 가야 하는데 차 좀 불러줘."),
    ("new_06_exact_library", "어르신: 내일 오후 1시에 집 앞에서 중앙도서관까지 차 좀 불러줘."),
    ("new_07_city_office", "어르신: 구청에 민원 보러 가야 해."),
    ("new_08_convenience_store", "어르신: 편의점에 생필품 사러 가야 하는데 차 좀 불러줘."),
    ("new_09_no_drt_family", "어르신: 병원은 가야 하는데 아들이 데려다준대. 차는 안 불러도 돼."),
    ("new_10_emergency_fall", "어르신: 방금 넘어졌는데 못 일어나겠어. 움직일 수가 없어."),
]

RUN_SESSION_TESTS = False

SESSION_TESTS = [
    (),
]

OUTPUT_KEYS = [
    "dialogue_stage", "drt_status", "destination_category", "destination_candidates",
    "symptom_keywords", "medical_department_candidates", "medical_clarification_required",
    "medical_clarification_question", "extracted_keywords", "missing_slots",
    "reservation_consent", "guardian_notify_consent", "mobility_difficulty",
    "emergency_risk", "confidence", "reason", "next_question", "guardian_message",
    "place_resolution_required", "place_resolution_method", "place_resolution_question",
    "sk_category", "search_keywords", "search_mode",
    "origin_full_address", "destination_full_address",
    "address_confirmation_required", "address_confirmation_question",
]

CATEGORIES = [
    "medical_general", "medical_dental", "medical_orthopedics", "medical_dermatology",
    "medical_internal", "medical_neurology", "medical_ophthalmology", "medical_ent",
    "medical_rehabilitation", "pharmacy", "shopping_market", "shopping_mart", "shopping_convenience",
    "public_community_center", "public_city_office", "public_bank",
    "welfare_center", "senior_center",
    "leisure_park", "leisure_culture_center", "leisure_library",
    "exercise_gym", "exercise_swimming", "exercise_sports_center",
    "religious_church", "religious_catholic", "religious_temple",
    "social_family_visit", "social_friend_visit",
    "unknown",
]

PLACE_WORD = {
    "medical_general": "병원", "medical_dental": "치과", "medical_orthopedics": "정형외과",
    "medical_dermatology": "피부과", "medical_internal": "내과", "medical_neurology": "신경과",
    "medical_ophthalmology": "안과", "medical_ent": "이비인후과",
    "medical_rehabilitation": "재활의학과", "pharmacy": "약국", "shopping": "시장이나 마트",
    "public_office": "주민센터", "welfare": "복지관", "leisure_park": "공원",
    "exercise": "운동 시설", "religious": "종교 시설", "social_visit": "방문 장소",
    "unknown": "목적지","shopping_market": "시장", "shopping_mart": "마트",
    "shopping_convenience": "편의점", "public_community_center": "주민센터",
    "public_city_office": "구청이나 시청", "public_bank": "은행",
    "welfare_center": "복지관", "senior_center": "경로당",
    "leisure_culture_center": "문화센터", "leisure_library": "도서관",
    "exercise_gym": "헬스장", "exercise_swimming": "수영장",
    "exercise_sports_center": "체육관", "religious_church": "교회",
    "religious_catholic": "성당", "religious_temple": "절",
    "social_family_visit": "가족 방문 장소", "social_friend_visit": "친구 방문 장소",
}

GENERIC_PLACES = [
    "병원", "치과", "정형외과", "피부과", "내과", "신경과", "안과", "이비인후과", "재활의학과",
    "약국", "시장", "마트", "편의점",
    "주민센터", "행정복지센터", "구청", "시청", "군청", "은행",
    "복지관", "경로당", "노인정",
    "공원", "문화센터", "도서관",
    "교회", "성당", "절",
    "헬스장", "수영장", "체육관"
]

PLACE_SUFFIXES = [
    "치과", "정형외과", "피부과", "내과", "신경과", "안과", "이비인후과", "재활의학과",
    "병원", "의원", "약국",
    "시장", "마트", "편의점",
    "주민센터", "행정복지센터", "구청", "시청", "군청", "은행",
    "복지관", "경로당", "노인정",
    "공원", "문화센터", "도서관",
    "교회", "성당", "절",
    "헬스장", "수영장", "체육관"
]


# =============================
# Basic helpers
# =============================

def normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))

def strip_speaker(text: str) -> str:
    return re.sub(r"(어르신|상담사|시스템)\s*:", " ", str(text or "")).strip()

#문장 안에 특정 표현들이 들어있는지 확인
def has_any(text: str, patterns: List[str]) -> bool:
    compact = normalize(text)
    return any(normalize(p) in compact for p in patterns)

def first_match(text: str, patterns: List[str]) -> Optional[str]:
    compact = normalize(text)
    for p in patterns:
        if normalize(p) in compact:
            return p
    return None

def unique(items: List[str]) -> List[str]:
    out: List[str] = []
    for item in items:
        if isinstance(item, str):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out

def has_final_consonant(word: str) -> bool:
    if not word:
        return False
    ch = word[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - ord("가")) % 28 != 0
    return False

def subject_particle(word: str) -> str:
    return "이" if has_final_consonant(word) else "가"

def direction_particle(word: str) -> str:
    if not word or not ("가" <= word[-1] <= "힣"):
        return "로"
    jong = (ord(word[-1]) - ord("가")) % 28
    return "로" if jong == 0 or jong == 8 else "으로"

def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ["true", "yes", "1", "예", "네", "맞음"]:
            return True
        if v in ["false", "no", "0", "아니", "아님", "없음"]:
            return False
    return default

def as_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return unique([x for x in value if isinstance(x, str) and len(x.strip()) <= 40])

def pick(value: Any, allowed: List[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


# =============================
# Rule detection
# =============================

def detect_emergency(text: str) -> bool:
    strong_emergency = has_any(text, [
        "숨이 차", "숨이 너무 차", "숨이 안 쉬", "호흡이 힘",
        "가슴이 답답", "가슴이 아프", "식은땀",
        "쓰러졌", "말이 잘 안 나와", "말이 안 나와",
        "한쪽 힘이 빠", "정신이 멍", "119", "응급실"
    ])

    fall_negative = has_any(text, ["넘어지진 않았", "넘어지지는 않았", "넘어진 건 아니", "낙상은 아니"])

    severe_fall = (
        has_any(text, ["넘어졌", "넘어져서", "낙상"])
        and not fall_negative
        and has_any(text, [
            "일어나기가 힘", "일어나기 힘", "못 일어나",
            "움직일 수가 없어", "움직일 수 없어",
            "움직일 수가 없", "움직일 수 없"
        ])
    )

    return strong_emergency or severe_fall

def detect_not_needed(text: str) -> Tuple[bool, bool]:
    refused = has_any(text, ["예약하지 마", "예약 안 해도 돼", "차 부르지 마", "안 불러도 돼", "아들이 데려다준대", "딸이 데려다준대"])
    not_needed = has_any(text, ["집에서 쉴래", "집에 있을래", "안 가도 될 것 같아", "오늘은 안 가", "안 나갈래", "취소할래"])
    return refused or not_needed, refused

def detect_reservation_request(text: str) -> bool:
    return has_any(text, ["차 좀 불러줘", "차 불러줘", "차량 예약해줘", "이동 차량 예약해줘", "DRT 예약해줘", "예약해줘", "불러줘"])

def detect_visit_intent(text: str) -> bool:
    if has_any(text, ["가야 하나 싶", "받아야 하나 싶", "가야 할까", "받아야 할까"]):
        return False
    return has_any(text, ["갈 거야", "갈거야", "가야", "가려고", "가고 싶", "방문", "진료", "치료", "받으러", "사러", "장보러", "서류", "예배", "친구 만나러"])

def detect_mobility_difficulty(text: str, reservation_request: bool) -> bool:
    if reservation_request:
        return True
    return has_any(text, [
        "버스 타기 힘", "버스 타기가 힘", "버스 타기 어려", "버스 타기가 어려",
        "걷기 힘", "걷기가 힘", "걷기 어려", "걷기가 어려",
        "혼자 가기 힘", "혼자 가기가 힘", "혼자 가기 어려", "혼자 가기가 어려",
        "차가 없어", "멀어서 못 가", "다리가 불편", "허리가 불편",
        "이동이 힘", "이동하기 힘", "움직이기 힘"
    ])

def extract_date(text: str) -> Optional[str]:
    return first_match(text, ["오늘", "내일", "모레", "다음 주", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"])

def extract_time(text: str) -> Optional[str]:
    m = re.search(r"(오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분|\s*반)?", text)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None

def extract_pickup(text: str) -> Optional[str]:
    return first_match(text, ["우리 집 앞", "우리집 앞", "집 앞", "집에서", "우리 집", "우리집", "자택", "아파트 앞", "경로당 앞", "복지관 앞"])

def extract_full_address(text: str) -> Tuple[str, str]:
    # 프로토타입용 간단 주소 추출: 실제 서비스에서는 주소 API 결과로 대체 예정
    addr_pattern = r"([가-힣A-Za-z0-9\s]+(?:시|군|구)\s*[가-힣A-Za-z0-9\s]*(?:동|읍|면|로|길)\s*\d*(?:-\d*)?)"
    found = [x.strip() for x in re.findall(addr_pattern, text) if len(x.strip()) >= 6]
    if "출발" in text and "도착" in text and len(found) >= 2:
        return found[0], found[1]
    return "", ""

def extract_specific_place(text: str) -> Optional[str]:
    raw = strip_speaker(text)
    candidates: List[str] = []
    for suffix in PLACE_SUFFIXES:
        pattern = rf"([가-힣A-Za-z0-9]{{2,12}}{suffix})"
        candidates.extend(re.findall(pattern, raw))
    for c in candidates:
        if c not in GENERIC_PLACES:
            return c
    return None

def category_from_place(place: Optional[str]) -> str:
    if not place:
        return "unknown"
    if place.endswith("치과"): return "medical_dental"
    if place.endswith("정형외과"): return "medical_orthopedics"
    if place.endswith("피부과"): return "medical_dermatology"
    if place.endswith("내과"): return "medical_internal"
    if place.endswith("신경과"): return "medical_neurology"
    if place.endswith("안과"): return "medical_ophthalmology"
    if place.endswith("이비인후과"): return "medical_ent"
    if place.endswith("재활의학과"): return "medical_rehabilitation"
    if place.endswith(("병원", "의원")): return "medical_general"
    if place.endswith("약국"): return "pharmacy"

    if place.endswith("시장"): return "shopping_market"
    if place.endswith("마트"): return "shopping_mart"
    if place.endswith("편의점"): return "shopping_convenience"

    if place.endswith(("주민센터", "행정복지센터")): return "public_community_center"
    if place.endswith(("구청", "시청", "군청")): return "public_city_office"
    if place.endswith("은행"): return "public_bank"

    if place.endswith("복지관"): return "welfare_center"
    if place.endswith(("경로당", "노인정")): return "senior_center"

    if place.endswith("공원"): return "leisure_park"
    if place.endswith("문화센터"): return "leisure_culture_center"
    if place.endswith("도서관"): return "leisure_library"

    if place.endswith("헬스장"): return "exercise_gym"
    if place.endswith("수영장"): return "exercise_swimming"
    if place.endswith("체육관"): return "exercise_sports_center"

    if place.endswith("교회"): return "religious_church"
    if place.endswith("성당"): return "religious_catholic"
    if place.endswith("절"): return "religious_temple"

    return "unknown"

def infer_destination(text: str) -> Tuple[str, List[str], Optional[str]]:
    specific = extract_specific_place(text)
    if specific:
        category = category_from_place(specific)
        return category, [specific], specific

    # 명시적 진료과/장소 우선. v5_04 같은 LLM 오판 방지용 핵심 규칙.
    rules = [
        ("medical_dental", ["치과", "치아", "이가", "잇몸", "치통"], ["치과"]),
        ("medical_dermatology", ["피부과", "피부", "상처", "까졌", "찢어졌", "피가"], ["피부과"]),
        ("medical_orthopedics", ["정형외과", "무릎", "허리", "관절", "근육", "뼈", "골절"], ["정형외과"]),
        ("medical_rehabilitation", ["재활", "물리치료"], ["재활의학과", "정형외과"]),
        ("medical_internal", ["내과", "속", "배가", "복통", "소화", "기침", "열이"], ["내과"]),
        ("medical_neurology", ["신경과", "두통", "어지러", "손발 저림"], ["신경과"]),
        ("medical_ophthalmology", ["안과", "눈이", "시야", "눈"], ["안과"]),
        ("medical_ent", ["이비인후과", "귀", "목", "코", "콧물", "인후"], ["이비인후과"]),
        ("pharmacy", ["약국", "약 받", "처방전", "약이"], ["약국"]),
        ("shopping_market", ["시장", "재래시장", "전통시장"], ["시장"]),
        ("shopping_convenience", ["편의점"], ["편의점"]),
        ("shopping_mart", ["마트", "장보"], ["마트"]),

        ("public_city_office", ["구청", "시청", "군청"], ["구청"]),
        ("public_community_center", ["주민센터", "행정복지센터", "등본"], ["주민센터"]),
        ("public_bank", ["은행", "통장", "입금", "출금"], ["은행"]),

        ("welfare_center", ["복지관"], ["복지관"]),
        ("senior_center", ["경로당", "노인정"], ["경로당"]),

        ("leisure_park", ["공원", "산책", "바람"], ["공원"]),
        ("leisure_culture_center", ["문화센터", "문화 강좌"], ["문화센터"]),
        ("leisure_library", ["도서관", "책 빌리"], ["도서관"]),

        ("exercise_gym", ["헬스장"], ["헬스장"]),
        ("exercise_swimming", ["수영장"], ["수영장"]),
        ("exercise_sports_center", ["체육관", "운동"], ["체육관"]),

        ("religious_church", ["교회", "예배"], ["교회"]),
        ("religious_catholic", ["성당", "미사"], ["성당"]),
        ("religious_temple", ["절", "법회"], ["절"]),

        ("social_family_visit", ["아들 집", "딸 집", "자식 집", "가족"], ["가족 방문 장소"]),
        ("social_friend_visit", ["친구", "지인", "모임"], ["친구 방문 장소"]),

        # 병원이라는 일반 표현은 모든 세부 진료과 규칙 뒤에 둔다.
        ("medical_general", ["병원", "진료", "검진", "건강검진"], ["병원"]),
    ]
    for category, keywords, candidates in rules:
        if has_any(text, keywords):
            return category, candidates, None
    return "unknown", [], None

def detect_place_preference(text: str) -> str:
    if has_any(text, ["가까운", "근처", "추천", "아무 데나", "아무데나"]):
        return "nearby"
    if has_any(text, ["평소 다니는", "자주 가는", "단골", "항상 가던", "다니던"]):
        return "frequent"
    return "unknown"


# =============================
# Medical clarification
# =============================

def infer_medical_detail(text: str, category: str, candidates: List[str]) -> Dict[str, Any]:
    symptoms: List[str] = []
    departments: List[str] = []
    required = False
    question = ""

    if has_any(text, ["다리", "무릎", "허리", "관절"]):
        if has_any(text, ["무릎", "허리", "관절", "뼈", "근육"]):
            symptoms.append("근골격계 통증")
        elif "다리" in text:
            symptoms.append("다리 통증")

    fall_negative = has_any(text, ["넘어지진 않았", "넘어지지는 않았", "넘어진 건 아니", "낙상은 아니"])

    if has_any(text, ["넘어졌", "넘어져서", "넘어", "낙상"]) and not fall_negative:
        symptoms.append("넘어짐")
    if has_any(text, ["피부", "상처", "까졌", "피가"]):
        symptoms.append("피부 상처")
    if has_any(text, ["치아", "이가", "잇몸", "치통"]):
        symptoms.append("치아 통증")

    # category별 진료과 후보
    if category == "medical_general":
        departments = ["내과", "정형외과", "피부과", "신경과", "안과", "이비인후과"]
        required = True
        question = "어디가 불편해서 병원에 가시려는 걸까요?"

    if category == "medical_orthopedics":
        departments = ["정형외과"]
    if category == "medical_dermatology":
        departments = ["피부과"]
    if category == "medical_dental":
        departments = ["치과"]
    if category == "medical_internal":
        departments = ["내과"]
    if category == "medical_neurology":
        departments = ["신경과"]
    if category == "medical_ophthalmology":
        departments = ["안과"]
    if category == "medical_ent":
        departments = ["이비인후과"]
    if category == "medical_rehabilitation":
        departments = ["재활의학과", "정형외과"]

    # 다리 통증만 있고 피부/관절이 안 갈리면 추가 질문
    if category in ["medical_general", "medical_orthopedics"] and has_any(text, ["다리"]) and not has_any(text, ["무릎", "관절", "뼈", "근육", "피부", "상처", "까졌"]):
        departments = ["피부과", "정형외과"]
        required = True
        question = "넘어져서 피부나 상처가 아픈 건가요, 아니면 뼈나 근육·관절 쪽이 아픈 건가요?"

    return {
        "symptom_keywords": unique(symptoms),
        "medical_department_candidates": unique(departments),
        "medical_clarification_required": required,
        "medical_clarification_question": question,
}


# =============================
# Gemini semantic analysis
# =============================

def default_semantic() -> Dict[str, Any]:
    return {
        "visit_intent": False, "reservation_request": False,
        "reservation_consent": "not_confirmed", "outing_status": "unknown",
        "destination_category": "unknown", "destination_candidates": [],
        "specific_place": "", "place_preference": "unknown",
        "mobility_difficulty": False, "emergency_risk": False,
        "reservation_completed": False, "guardian_notify_consent": "not_asked",
        "extracted_keywords": [], "reason": "",
    }

def build_prompt(conversation: str) -> str:
    return f"""
너는 고령층 AI 케어콜 발화의 의미만 분석한다.
반드시 JSON 객체 하나만 출력한다. 설명문, 코드블록, 주석은 쓰지 않는다.

출력 key:
visit_intent, reservation_request, reservation_consent, outing_status,
destination_category, destination_candidates, specific_place, place_preference,
mobility_difficulty, emergency_risk, reservation_completed,
guardian_notify_consent, extracted_keywords, reason

허용 category:
{", ".join(CATEGORIES)}

규칙:
- 날짜, 시간, missing_slots, next_question은 만들지 않는다.
- 차 좀 불러줘/차량 예약해줘/예약해줘는 reservation_request true.
- 병원/치과/약국처럼 대분류만 있으면 specific_place는 빈 문자열.
- 행복병원/중앙약국처럼 고유 장소명이 있으면 specific_place에 넣는다.
- 가까운/근처는 place_preference nearby.
- 평소 다니는/자주 가는은 place_preference frequent.
- 단순 통증만으로 emergency_risk true를 만들지 않는다.
- 숨참/가슴 답답/말이 안 나옴/넘어져 못 일어남 등만 emergency_risk true.

상담 대화:
{conversation.strip()}
"""

def call_gemini(conversation: str) -> Optional[Dict[str, Any]]:
    global GEMINI_TEMP_DISABLED

    if not USE_GEMINI or GEMINI_TEMP_DISABLED:
        return None

    api_key = os.getenv("GEMINI_KEY")
    if not api_key:
        print("주의: GEMINI_KEY가 없어 규칙 기반 분석으로 진행합니다.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=build_prompt(conversation),
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )

        if SHOW_RAW_GEMINI:
            print("\n--- Gemini raw output ---")
            print(response.text)

        return json.loads(response.text)

    except Exception as e:
        err = str(e)

        if "429" in err or "RESOURCE_EXHAUSTED" in err or "Quota exceeded" in err:
            GEMINI_TEMP_DISABLED = True
            print("주의: Gemini 무료 요청 한도를 초과하여 이번 실행에서는 규칙 기반 분석으로 진행합니다.")
        else:
            print(f"주의: Gemini 호출 실패. 규칙 기반 분석으로 진행합니다. ({type(e).__name__})")

        return None

def sanitize_semantic(raw: Optional[Dict[str, Any]], text: str) -> Dict[str, Any]:
    data = default_semantic()
    if isinstance(raw, dict):
        data.update(raw)

    rule_category, rule_candidates, rule_specific = infer_destination(text)
    reservation_request = detect_reservation_request(text)
    not_needed, refused = detect_not_needed(text)

    data["visit_intent"] = as_bool(data.get("visit_intent"), detect_visit_intent(text) or reservation_request)
    data["reservation_request"] = as_bool(data.get("reservation_request"), reservation_request)
    data["reservation_consent"] = pick(data.get("reservation_consent"), ["confirmed", "not_confirmed", "refused", "unknown"], "not_confirmed")
    data["outing_status"] = pick(data.get("outing_status"), ["intended", "not_needed", "refused", "unknown"], "unknown")
    data["destination_category"] = pick(data.get("destination_category"), CATEGORIES, "unknown")
    data["destination_candidates"] = as_list(data.get("destination_candidates"))
    data["specific_place"] = data.get("specific_place") if isinstance(data.get("specific_place"), str) else ""
    data["place_preference"] = pick(data.get("place_preference"), ["unknown", "nearby", "frequent", "exact", "direct_address_required"], "unknown")
    data["mobility_difficulty"] = as_bool(data.get("mobility_difficulty"), False)
    data["emergency_risk"] = as_bool(data.get("emergency_risk"), False)
    data["reservation_completed"] = as_bool(data.get("reservation_completed"), False)
    data["guardian_notify_consent"] = pick(data.get("guardian_notify_consent"), ["confirmed", "not_asked", "refused", "unknown"], "not_asked")
    data["extracted_keywords"] = as_list(data.get("extracted_keywords"))
    data["reason"] = data.get("reason") if isinstance(data.get("reason"), str) else ""

    # 핵심 보호 규칙: 목적지/응급/예약요청/이동어려움은 최종적으로 규칙이 보호한다.
    if rule_category != "unknown":
        data["destination_category"] = rule_category
        data["destination_candidates"] = rule_candidates
    if rule_specific:
        data["specific_place"] = rule_specific
        data["place_preference"] = "exact"
    else:
        data["specific_place"] = "" if data["specific_place"] not in normalize(text) else data["specific_place"]

    rule_preference = detect_place_preference(text)
    if rule_preference != "unknown":
        data["place_preference"] = rule_preference

    if reservation_request and not not_needed:
        data["reservation_request"] = True
        data["reservation_consent"] = "confirmed"
        data["visit_intent"] = True
        data["outing_status"] = "intended"

    if detect_visit_intent(text):
        data["visit_intent"] = True

    data["mobility_difficulty"] = detect_mobility_difficulty(text, data["reservation_request"])
    data["emergency_risk"] = detect_emergency(text)

    if not_needed:
        data["outing_status"] = "refused" if refused else "not_needed"
        data["reservation_request"] = False
        data["reservation_consent"] = "refused" if refused else "not_confirmed"

    if has_any(text, ["예약이 완료되었습니다", "DRT 예약이 완료되었습니다", "예약 완료"]):
        data["reservation_completed"] = True
        data["reservation_consent"] = "confirmed"

    if has_any(text, ["알리지 마", "보내지 마", "말하지 마"]):
        data["guardian_notify_consent"] = "refused"
    elif has_any(text, ["보호자에게 알려줘", "딸한테 알려줘", "아들한테 알려줘"]):
        data["guardian_notify_consent"] = "confirmed"

    if data["destination_category"].startswith("social_"):
        data["place_preference"] = "direct_address_required"

    return data


# =============================
# Final composition
# =============================

def get_search_info(category: str, text: str) -> Tuple[str, List[str]]:
    # 내부 category를 실제 장소 검색 API용 category/keyword로 변환한다.
    # SK API category 명칭은 추후 실제 문서에 맞춰 조정하고, 현재는 search_keywords 중심으로 사용한다.
    if category.startswith("medical_"):
        return "병원", [PLACE_WORD.get(category, "병원")]

    if category == "pharmacy": return "약국", ["약국"]

    if category == "shopping_market": return "대형유통점", ["시장"]
    if category == "shopping_mart": return "마트", ["마트"]
    if category == "shopping_convenience": return "편의점", ["편의점"]

    if category == "public_community_center": return "생활서비스", ["주민센터"]
    if category == "public_city_office": return "공공기관", ["구청", "시청"]
    if category == "public_bank": return "금융", ["은행"]

    if category == "welfare_center": return "생활서비스", ["복지관"]
    if category == "senior_center": return "생활서비스", ["경로당"]

    if category == "leisure_park": return "관광지", ["공원"]
    if category == "leisure_culture_center": return "문화생활", ["문화센터"]
    if category == "leisure_library": return "문화생활", ["도서관"]

    if category == "exercise_gym": return "레저/스포츠", ["헬스장"]
    if category == "exercise_swimming": return "레저/스포츠", ["수영장"]
    if category == "exercise_sports_center": return "레저/스포츠", ["체육관"]

    if category in ["religious_church", "religious_catholic", "religious_temple"]:
        return "문화생활", [PLACE_WORD.get(category, "종교 시설")]

    if category.startswith("social_"):
        return "", []

    return "", []

def stage_and_status(s: Dict[str, Any]) -> Tuple[str, str, str, str]:
    if s["reservation_completed"] and s["guardian_notify_consent"] == "confirmed":
        return "guardian_notification", "reserved", "confirmed", "confirmed"
    if s["reservation_completed"]:
        return "reservation_completed", "reserved", "confirmed", s["guardian_notify_consent"] if s["guardian_notify_consent"] == "refused" else "not_asked"
    if s["emergency_risk"]:
        return "emergency", "emergency", "not_confirmed", "not_asked"
    if s["outing_status"] in ["not_needed", "refused"] or s["reservation_consent"] == "refused":
        return "not_needed", "not_needed", "refused" if s["reservation_consent"] == "refused" else "not_confirmed", "not_asked"
    if s["reservation_request"] or s["reservation_consent"] == "confirmed":
        return "reservation_info_collection", "needed", "confirmed", "not_asked"
    if s["visit_intent"]:
        return "reservation_confirm", "possible", "not_confirmed", "not_asked"
    return "need_detection", "possible" if s["destination_category"] != "unknown" else "unclear", "not_confirmed", "not_asked"

def build_place_resolution(stage: str, category: str, candidates: List[str], specific_place: Optional[str], preference: str, text: str) -> Dict[str, Any]:
    sk_category, search_keywords = get_search_info(category, text)

    if stage in ["emergency", "not_needed", "need_detection", "reservation_completed", "guardian_notification"]:
        return {
            "place_resolution_required": False,
            "place_resolution_method": "not_applicable",
            "place_resolution_question": "",
            "sk_category": sk_category,
            "search_keywords": search_keywords,
            "search_mode": "not_applicable",
        }

    if specific_place:
        return {
            "place_resolution_required": False,
            "place_resolution_method": "exact_place",
            "place_resolution_question": "",
            "sk_category": sk_category,
            "search_keywords": search_keywords,
            "search_mode": "exact_place",
        }

    if category.startswith("social_"):
        return {
            "place_resolution_required": True,
            "place_resolution_method": "exact_place_required",
            "place_resolution_question": "방문하실 곳의 주소나 정확한 장소명을 알려주실 수 있을까요?",
            "sk_category": "",
            "search_keywords": candidates,
            "search_mode": "direct_address_required",
        }

    if category == "unknown":
        return {
            "place_resolution_required": False,
            "place_resolution_method": "not_applicable",
            "place_resolution_question": "",
            "sk_category": "",
            "search_keywords": [],
            "search_mode": "not_applicable",
        }

    place = PLACE_WORD.get(category, "목적지")

    if preference == "nearby":
        return {
            "place_resolution_required": False,
            "place_resolution_method": "nearby_search",
            "place_resolution_question": "",
            "sk_category": sk_category,
            "search_keywords": search_keywords,
            "search_mode": "nearby_search",
        }

    if preference == "frequent":
        return {
            "place_resolution_required": True,
            "place_resolution_method": "frequent_place",
            "place_resolution_question": f"자주 가시는 {place} 이름을 알려주실 수 있을까요?",
            "sk_category": sk_category,
            "search_keywords": search_keywords,
            "search_mode": "ask_exact_place_name",
        }

    return {
        "place_resolution_required": True,
        "place_resolution_method": "unknown",
        "place_resolution_question": f"평소 자주 가시는 {place}{subject_particle(place)} 있으실까요? 아니면 가까운 {place}{direction_particle(place)} 안내해드릴까요?",
        "sk_category": sk_category,
        "search_keywords": search_keywords,
        "search_mode": "ask_frequent_or_nearby",
    }

def build_missing(stage: str, date: Optional[str], time_: Optional[str], pickup: Optional[str], medical: Dict[str, Any], place_info: Dict[str, Any], origin_addr: str, dest_addr: str) -> List[str]:
    if stage in ["emergency", "not_needed", "reservation_completed", "guardian_notification"]:
        return []
    if stage == "need_detection":
        return ["visit_intent", "reservation_consent"]

    slots: List[str] = []

    if medical["medical_clarification_required"]:
        slots.append("medical_department")

    if place_info["place_resolution_required"]:
        if place_info["place_resolution_method"] == "unknown":
            slots.append("place_resolution_method")
        else:
            slots.append("exact_destination")

    if stage == "reservation_confirm":
        slots.append("reservation_consent")
        return unique(slots)

    if not date: slots.append("date")
    if not time_: slots.append("time")
    if not pickup: slots.append("pickup_location")

    # 실제 호출 직전 전체 주소 확인
    core_ready = not any(x in slots for x in ["date", "time", "pickup_location", "exact_destination", "place_resolution_method", "medical_department"])

    if stage == "reservation_info_collection" and core_ready:
        search_mode = place_info.get("search_mode", "")

        if search_mode == "nearby_search":
            # 가까운 장소 검색은 출발지 기준으로 API 검색을 하므로
            # 사용자가 도착지 전체 주소를 직접 말할 필요는 없다.
            if not origin_addr:
                slots.append("origin_full_address")

        elif search_mode == "exact_place":
            # 정확한 장소명이 있는 경우에는 실제 호출 전 출발지/도착지 주소 확인 필요
            if not origin_addr:
                slots.append("origin_full_address")
            if not dest_addr:
                slots.append("destination_full_address")

        else:
            if not origin_addr:
                slots.append("origin_full_address")
            if not dest_addr:
                slots.append("destination_full_address")

    return unique(slots)

def build_next_question(stage: str, missing: List[str], category: str, medical: Dict[str, Any], place_info: Dict[str, Any], date: Optional[str], time_: Optional[str], pickup: Optional[str], specific_place: Optional[str]) -> str:
    if stage == "emergency":
        return "지금 바로 보호자나 119에 연결해드릴까요?"

    if stage in ["not_needed", "reservation_completed", "guardian_notification"]:
        return ""

    # 병원 일반 케이스는 교수님 피드백처럼 진료과/증상 확인을 먼저 한다.
    if "medical_department" in missing:
        return medical["medical_clarification_question"]

    # reservation_confirm 단계에서는 장소 구체화보다 예약 동의를 먼저 묻는다.
    # 예: 은행 가야 해 → 은행에 가시는 이동 차량 예약을 도와드릴까요?
    # 예: 친구 만나러 가고 싶어 → 친구 방문 장소에 가시는 이동 차량 예약을 도와드릴까요?
    if stage == "reservation_confirm" and "reservation_consent" in missing:
        return f"{PLACE_WORD.get(category, '목적지')}에 가시는 이동 차량 예약을 도와드릴까요?"

    # 예약 동의가 이미 확인된 reservation_info_collection 단계에서는 목적지 구체화 질문을 먼저 한다.
    if "place_resolution_method" in missing or "exact_destination" in missing:
        return place_info["place_resolution_question"]

    if "reservation_consent" in missing:
        return f"{PLACE_WORD.get(category, '목적지')}에 가시는 이동 차량 예약을 도와드릴까요?"

    if "date" in missing and "time" in missing:
        return "가실 날짜와 시간을 알려주실 수 있을까요?"

    if "date" in missing:
        return "가실 날짜를 알려주실 수 있을까요?"

    if "time" in missing:
        return "가실 시간을 알려주실 수 있을까요?"

    if "pickup_location" in missing:
        return "출발하실 위치를 알려주실 수 있을까요?"

    if "origin_full_address" in missing and "destination_full_address" not in missing:
        return "가까운 장소를 찾기 위해 출발지의 전체 주소가 필요합니다. 출발지 전체 주소를 알려주실 수 있을까요?"

    if "destination_full_address" in missing and "origin_full_address" not in missing:
        return "실제 차량 호출 전 확인을 위해 도착지의 전체 주소가 필요합니다. 도착지 전체 주소를 알려주실 수 있을까요?"

    if "origin_full_address" in missing or "destination_full_address" in missing:
        return "실제 차량 호출 전 확인을 위해 출발지와 도착지의 전체 주소가 필요합니다. 출발지 전체 주소와 도착지 전체 주소를 알려주실 수 있을까요?"

    dest = specific_place or PLACE_WORD.get(category, "목적지")
    summary = " ".join(x for x in [date, time_] if x)
    return f"{summary}, {pickup or '출발지'}에서 {dest}까지 예약을 진행해드릴까요?"

def build_keywords(text: str, llm_keywords: List[str], *items: Any) -> List[str]:
    keywords = as_list(llm_keywords)
    for item in items:
        if isinstance(item, str) and item:
            keywords.append(item)
        elif isinstance(item, list):
            keywords.extend([x for x in item if isinstance(x, str)])
    for phrase in ["차 좀 불러줘", "차량 예약해줘", "이동 차량 예약해줘", "버스 타기가 힘들어", "집에서 쉴래", "알리지 마", "숨이 너무 차", "가슴이 답답", "병원 갈 거야", "다리가 아파", "피부가 까졌어"]:
        if has_any(text, [phrase]):
            keywords.append(phrase)
    return unique(keywords)

def build_reason(stage: str, category: str, missing: List[str], medical: Dict[str, Any]) -> str:
    place = PLACE_WORD.get(category, "목적지")
    if stage == "emergency":
        return "응급 가능성이 있는 표현이 있어 DRT 예약보다 보호자 또는 119 연결이 우선입니다."
    if stage == "not_needed":
        return "외출 의도가 없거나 DRT 예약을 원하지 않는다고 표현했습니다."
    if medical["medical_clarification_required"]:
        return "병원 방문 의향은 있으나 증상 또는 진료과가 아직 구체화되지 않았습니다."
    if stage == "reservation_confirm":
        return f"{place} 방문 의향은 표현되었으나 DRT 예약 동의는 아직 확인되지 않았습니다."
    if stage == "reservation_info_collection":
        return f"{place} 방문 목적과 DRT 예약 요청이 확인되었으며, 필요한 예약 정보를 수집하는 단계입니다."
    if stage == "reservation_completed":
        return "DRT 예약이 완료된 상태입니다."
    if stage == "guardian_notification":
        return "예약 완료 후 보호자에게 예약 정보를 공유하는 데 동의했습니다."
    return "대화 내용에 따라 DRT 관련 상태를 판단했습니다."

def compose_result(conversation: str, semantic: Dict[str, Any]) -> Dict[str, Any]:
    date = extract_date(conversation)
    time_ = extract_time(conversation)
    pickup = extract_pickup(conversation)
    origin_addr, dest_addr = extract_full_address(conversation)

    stage, drt_status, reservation_consent, guardian_consent = stage_and_status(semantic)
    category = semantic["destination_category"]
    candidates = semantic["destination_candidates"]
    specific_place = semantic["specific_place"] or None

    if stage == "emergency":
        category, candidates, specific_place = "unknown", [], None
    if stage == "not_needed" and semantic["outing_status"] != "refused":
        category, candidates, specific_place = "unknown", [], None

    medical = infer_medical_detail(conversation, category, candidates)

    # DRT가 필요 없는 단계에서는 추가 진료과 질문을 하지 않는다.
    if stage in ["not_needed", "emergency", "reservation_completed", "guardian_notification"]:
        medical["medical_clarification_required"] = False
        medical["medical_clarification_question"] = ""
        medical["medical_department_candidates"] = []

    # 정확한 병원명이 이미 나온 경우에는 진료과를 다시 묻지 않고,
    # 실제 호출 전 전체 주소 확인 단계로 넘어간다.        
    if specific_place and category.startswith("medical_"):
        medical["medical_clarification_required"] = False
        medical["medical_clarification_question"] = ""
        if category == "medical_general":
            medical["medical_department_candidates"] = []
    place_info = build_place_resolution(stage, category, candidates, specific_place, semantic["place_preference"], conversation)
    missing = build_missing(stage, date, time_, pickup, medical, place_info, origin_addr, dest_addr)
    next_question = build_next_question(stage, missing, category, medical, place_info, date, time_, pickup, specific_place)

    address_required = "origin_full_address" in missing or "destination_full_address" in missing
    guardian_message = ""
    if stage == "guardian_notification" and guardian_consent == "confirmed":
        guardian_message = f"{date or '예약일'} {time_ or '예약 시간'}, {pickup or '출발지'}에서 {specific_place or PLACE_WORD.get(category, '목적지')}까지 DRT 차량이 예약되었습니다."

    if stage in ["reservation_completed", "guardian_notification"]:
        semantic["mobility_difficulty"] = False

    result = {
        "dialogue_stage": stage,
        "drt_status": drt_status,
        "destination_category": category,
        "destination_candidates": candidates,
        **medical,
        "extracted_keywords": build_keywords(conversation, semantic["extracted_keywords"], date, time_, pickup, specific_place, candidates, medical["symptom_keywords"], medical["medical_department_candidates"]),
        "missing_slots": missing,
        "reservation_consent": reservation_consent,
        "guardian_notify_consent": guardian_consent,
        "mobility_difficulty": semantic["mobility_difficulty"],
        "emergency_risk": semantic["emergency_risk"],
        "confidence": 0.95 if stage in ["reservation_info_collection", "emergency", "not_needed"] else 0.85 if stage == "reservation_confirm" else 0.70,
        "reason": build_reason(stage, category, missing, medical),
        "next_question": next_question,
        "guardian_message": guardian_message,
        **place_info,
        "origin_full_address": origin_addr,
        "destination_full_address": dest_addr,
        "address_confirmation_required": address_required,
        "address_confirmation_question": next_question if address_required else "",
    }

    return {key: result.get(key) for key in OUTPUT_KEYS}

def analyze_conversation(conversation: str) -> Dict[str, Any]:
    raw = call_gemini(conversation)
    semantic = sanitize_semantic(raw, conversation)
    return compose_result(conversation, semantic)


def format_drt_summary(result: Dict[str, Any]) -> str:
    """케어콜 데모에서 매 턴 출력용 한 줄 요약."""
    parts = [
        f"stage={result['dialogue_stage']}",
        f"drt={result['drt_status']}",
        f"dest={result['destination_category']}",
    ]
    if result["missing_slots"]:
        parts.append(f"missing={result['missing_slots']}")
    if result["next_question"]:
        parts.append(f'next_q="{result["next_question"]}"')
    if result["emergency_risk"]:
        parts.append("emergency_risk=True")
    return "[DRT 분석] " + " ".join(parts)


def run_session_tests() -> None:
    for session_name, turns in SESSION_TESTS:
        print(f"\n\n==============================")
        print(f"세션 테스트 시작: {session_name}")
        print(f"==============================")

        history: List[str] = []

        for idx, turn in enumerate(turns, start=1):
            history.append(turn)

            # 현재는 이전 발화를 누적해서 전체 맥락으로 분석한다.
            conversation = "\n".join(history)

            print(f"\n--- {session_name} / turn_{idx} ---")
            print(turn)

            result = analyze_conversation(conversation)
            print(json.dumps(result, ensure_ascii=False, indent=2))

            if USE_GEMINI and REQUEST_DELAY_SEC > 0 and idx < len(turns):
                time.sleep(REQUEST_DELAY_SEC)

# =============================
# Main
# =============================

def main() -> None:
    if RUN_SESSION_TESTS:
        run_session_tests()
        return

    if SELECTED_TEST_NAME:
        cases = [case for case in TEST_CASES if case[0] == SELECTED_TEST_NAME]
        if not cases:
            raise ValueError(f"없는 테스트 이름입니다: {SELECTED_TEST_NAME}")
    else:
        cases = TEST_CASES

    for idx, (name, conversation) in enumerate(cases):
        print(f"\n답변 생성 중입니다: {name}")
        result = analyze_conversation(conversation)
        print(f"\n===== {name} 최종 출력 =====")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if USE_GEMINI and REQUEST_DELAY_SEC > 0 and idx < len(cases) - 1:
            time.sleep(REQUEST_DELAY_SEC)

if __name__ == "__main__":
    main()
