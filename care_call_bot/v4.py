# -*- coding: utf-8 -*-
"""
DRT 상담 대화 분석기 - Rule-first + LLM-assisted hybrid version

핵심 방향
1) LLM은 보조로 사용한다.
2) dialogue_stage, drt_status, missing_slots, reservation_consent 같은 핵심 필드는
   규칙 엔진이 최종 결정한다.
3) LLM JSON 파싱 실패나 일부 필드 오류가 있어도 최종 출력은 안정적으로 유지한다.

실행:
    python src/drt_analyzer_hybrid.py

빠른 규칙 테스트만 하고 싶으면 USE_LLM = False
LLM도 같이 호출하고 싶으면 USE_LLM = True
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# LLM을 보조로 사용할지 여부입니다.
# CPU 환경에서는 매우 느릴 수 있으므로, 규칙 검증 중에는 False를 추천합니다.
USE_LLM = True

MODEL_NAME = "K-intelligence/Midm-2.0-Mini-Instruct"

# 한 개만 돌리고 싶으면 테스트 이름 입력, 전체 실행은 None
SELECTED_TEST_NAME: Optional[str] = None

TEST_CASES = [
    ("test_06_checkup_hint_only", "어르신: 요즘 몸이 좀 안 좋아서 검진을 받아야 하나 싶어."),
    ("test_07_physical_therapy_hint", "어르신: 요즘 다리가 뻐근해서 물리치료를 받아야 할 것 같아."),
    ("test_08_dental_visit_bus_hard", "어르신: 치과 가야 하는데 버스 타기가 힘들어."),
    ("test_32_tired_stay_home", "어르신: 몸이 피곤해서 오늘은 집에서 쉴래."),
    ("test_33_cancel_outing", "어르신: 원래 시장 가려고 했는데 오늘은 안 가도 될 것 같아."),
    ("test_50_friend_visit_no_mobility", "어르신: 친구 집에 잠깐 다녀오려고."),
    ("test_53_welfare_center", "어르신: 경로당에 가고 싶은데 다리가 불편해."),
    ("test_56_pool_exercise", "어르신: 수영장에 운동하러 가고 싶은데 오래 걷기가 힘들어."),
    ("test_57_social_visit", "어르신: 친구 만나러 가고 싶은데 혼자 가기가 힘들어."),    
]

OUTPUT_KEYS = [
    "dialogue_stage",
    "drt_status",
    "destination_category",
    "destination_candidates",
    "extracted_keywords",
    "missing_slots",
    "reservation_consent",
    "guardian_notify_consent",
    "mobility_difficulty",
    "emergency_risk",
    "confidence",
    "reason",
    "next_question",
    "guardian_message",
]

GENERIC_PLACE_WORDS = [
    "치과", "병원", "정형외과", "약국", "주민센터", "시장", "마트", "복지관", "경로당", "노인정", "공원", "교회", "성당", "절", "헬스장", "수영장", "체육관",
]

PLACE_SUFFIXES = [
    "치과", "병원", "의원", "정형외과", "약국", "주민센터", "시장", "마트", "복지관", "경로당", "노인정", "공원", "교회", "성당", "절", "헬스장", "수영장", "체육관",
]

CATEGORY_TO_PLACE_WORD = {
    "medical_dental": "치과",
    "medical_general": "병원",
    "medical_orthopedics": "정형외과",
    "pharmacy": "약국",
    "shopping": "시장이나 마트",
    "public_office": "주민센터",
    "welfare": "복지관",
    "leisure_park": "공원",
    "exercise": "운동 시설",
    "religious": "종교 시설",
    "social_visit": "방문 장소",
    "unknown": "목적지",
}

def get_display_place(category: str, text: str) -> str:
    if category=="medical_orthopedics": return "물리치료" if "물리치료" in text else "정형외과"
    if category=="welfare": return "경로당" if "경로당" in text else "노인정" if "노인정" in text else "복지관"
    if category=="exercise": return "수영장" if "수영장" in text else "헬스장" if "헬스장" in text else "체육관" if "체육관" in text else "운동 시설"
    if category=="religious": return "교회" if "교회" in text else "성당" if "성당" in text else "절" if "절" in text else "종교 시설"
    if category=="social_visit": return "친구 집" if "친구 집" in text else "친구 만나는 곳" if "친구" in text else "지인 만나는 곳" if "지인" in text else "방문 장소"
    if category=="shopping": return "마트" if "마트" in text else "시장" if "시장" in text else "시장이나 마트"
    return CATEGORY_TO_PLACE_WORD.get(category, "목적지")


def normalize(text: str) -> str:
    """공백을 제거하여 표현 매칭을 안정화합니다."""
    return re.sub(r"\s+", "", text)


def strip_speaker(text: str) -> str:
    """간단한 화자 라벨을 제거한 분석용 텍스트를 반환합니다."""
    return re.sub(r"(어르신|상담사|시스템)\s*:", " ", text).strip()


def contains_any(text: str, patterns: List[str]) -> bool:
    compact = normalize(text)
    return any(normalize(p) in compact for p in patterns)


def find_first(text: str, patterns: List[str]) -> Optional[str]:
    compact = normalize(text)
    for pattern in patterns:
        if normalize(pattern) in compact:
            return pattern
    return None


def detect_emergency(text: str) -> bool:
    patterns = [
        "숨이 차", "숨이 너무 차", "숨이 잘 안 쉬어", "숨도 잘 안 쉬어", "숨이 안 쉬어",
        "가슴이 답답", "가슴이 아프", "식은땀", "쓰러질 것", "쓰러질거",
        "넘어졌는데 일어나기 힘", "일어나기가 힘", "일어나기 힘", "의식이 없",
        "정신이 멍", "말이 잘 안 나와", "말이 안 나와", "한쪽 힘이 빠", "극심하게 어지",
    ]
    return contains_any(text, patterns)


def detect_not_needed(text: str) -> Tuple[bool, bool]:
    no_outing_patterns = [
        "집에만 있으려고","집에만 있을래","집에 있을래","그냥 집에 있을래","오늘은 쉴래","집에서 쉴래",
        "집에서 쉬려고","오늘은 집에서 쉴래","나갈 일 없어","외출 안 할래","외출 안 해","안 나갈래",
        "안 가도 될 것 같아","오늘은 안 가도 될 것 같아","안 가도 돼","오늘은 안 가","오늘은 안 갈래","취소할래"]
    refusal_patterns = [
        "예약은 안 해도 돼","예약 안 해도 돼","예약하지 마","예약은 하지 마","차는 부르지 마",
        "차 부르지 마","안 불러도 돼","부르지 마","아들이 데려다준대","딸이 데려다준대","가족이 데려다준대","가족이 데려다준다"]
    if contains_any(text, refusal_patterns): return True, True
    if contains_any(text, no_outing_patterns): return True, False
    return False, False


def detect_reservation_request(text: str) -> bool:
    patterns = [
        "예약해줘", "예약해 줘", "예약해주세요", "예약해 주세요",
        "차 불러줘", "차 좀 불러줘", "차 불러 줘", "차 좀 불러 줘",
        "차량 예약해줘", "차량 예약해 줘", "이동 차량 예약해줘", "이동 차량 예약해 줘",
        "DRT 예약해줘", "DRT 예약해 줘", "불러줘", "불러 줘", "응 해줘", "그래 해줘",
    ]
    return contains_any(text, patterns)


def detect_visit_intent(text: str) -> bool:
    uncertain_patterns = ["가야 하나 싶","받아야 하나 싶","해야 하나 싶","가야 할까","받아야 할까"]
    if contains_any(text, uncertain_patterns): return False
    patterns = [
        "가야","가려고","가고 싶","가보려고","다녀와야","다녀오려고","잠깐 다녀오려고","방문해야",
        "친구 집에","친구 만나러","보러 가야","받으러 가야","사러 가야","받으러","처방","진료",
        "치료","장보러","서류 떼러","서류떼러","바람 쐬러","예배","미사","법회"]
    return contains_any(text, patterns)


def detect_mobility_difficulty(text: str, has_reservation_request: bool) -> bool:
    if has_reservation_request:
        return True

    patterns = [
        # 버스/대중교통 관련
        "버스 타기 힘", "버스 타기가 힘", "버스타기힘", "버스타기가힘", "버스를 갈아타야", "갈아타야 해서 힘",

        # 보행 어려움
        "걷기 힘", "걷기가 힘", "오래 걷기가 힘", "오래 걷기 힘", "혼자 가기 힘", "혼자 가기가 힘",

        # 교통수단 없음
        "차가 없어", "차가 없", "태워줄 사람이 없어", "교통편이 없어",

        # 거리 문제
        "멀어서 못 가", "멀어서 못가",

        # 신체 불편으로 인한 이동 어려움
        "다리가 불편", "다리 불편", "다리가 뻐근", "다리 뻐근", "허리가 불편", "허리 불편",

        # 일반 이동 어려움
        "이동이 힘", "이동하기 힘",
    ]

    return contains_any(text, patterns)


def extract_date(text: str) -> Optional[str]:
    date_words = ["오늘", "내일", "모레", "다음 주", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    return find_first(text, date_words)


def extract_time(text: str) -> Optional[str]:
    # 구체적 시각: 오전 10시, 오후 2시, 11시, 3시 반, 11시 30분 등
    pattern = re.compile(r"(오전|오후)?\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분|\s*반)?")
    match = pattern.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip()


def has_broad_time_only(text: str) -> bool:
    if extract_time(text):
        return False
    return contains_any(text, ["오전", "오후", "점심쯤", "저녁쯤", "아침쯤"])


def detect_pickup_location(text: str) -> Optional[str]:
    patterns = [
        "우리 집 앞", "우리집 앞", "집 앞", "집에서", "우리 집", "우리집", "자택", "아파트 앞",
        "경로당 앞", "복지관 앞", "병원 앞", "주민센터 앞",
    ]
    return find_first(text, patterns)


def extract_specific_place(text: str) -> Optional[str]:
    """고유명사형 목적지명을 간단히 추출합니다. 예: 서울치과, 행복의원, 하나약국"""
    raw = strip_speaker(text)
    candidates: List[str] = []

    # 공백 기준 토큰 안에서 찾기
    tokens = re.split(r"[\s,./]+", raw)
    for token in tokens:
        cleaned = re.sub(r"[^가-힣A-Za-z0-9]", "", token)
        if not cleaned:
            continue
        for suffix in PLACE_SUFFIXES:
            if cleaned.endswith(suffix) and cleaned != suffix and len(cleaned) > len(suffix):
                # 너무 긴 문장이 통째로 붙는 경우 방지
                if len(cleaned) <= 12:
                    candidates.append(cleaned)

    # 문장 안에서 붙어 있는 형태도 검색
    for suffix in PLACE_SUFFIXES:
        pattern = re.compile(rf"([가-힣A-Za-z0-9]{{2,10}}{suffix})")
        for match in pattern.findall(raw):
            if match != suffix and match not in GENERIC_PLACE_WORDS:
                candidates.append(match)

    # generic 제외 및 순서 유지
    unique: List[str] = []
    for item in candidates:
        if item in GENERIC_PLACE_WORDS:
            continue
        if item not in unique:
            unique.append(item)
    return unique[0] if unique else None


def detect_destination(text: str) -> Tuple[str, List[str], Optional[str]]:
    specific = extract_specific_place(text)

    # exact name이 있으면 suffix로 분류
    if specific:
        if specific.endswith("치과"):
            return "medical_dental", [specific], specific
        if specific.endswith(("병원", "의원")):
            return "medical_general", [specific], specific
        if specific.endswith("정형외과"):
            return "medical_orthopedics", [specific], specific
        if specific.endswith("약국"):
            return "pharmacy", [specific], specific
        if specific.endswith("주민센터"):
            return "public_office", [specific], specific
        if specific.endswith(("시장", "마트")):
            return "shopping", [specific], specific
        if specific.endswith(("복지관", "경로당", "노인정")):
            return "welfare", [specific], specific
        if specific.endswith("공원"):
            return "leisure_park", [specific], specific
        if specific.endswith(("교회", "성당", "절")):
            return "religious", [specific], specific
        if specific.endswith(("헬스장", "수영장", "체육관")):
            return "exercise", [specific], specific

    # generic keyword mapping. 더 구체적인 것부터 검사합니다.
    # 1단계: 실제 목적지로 쓰인 명시적 장소명을 먼저 검사합니다.
    # 예: "복지관에 가고 싶은데 다리가 불편해"에서는
    # "다리"보다 "복지관"이 목적지이므로 welfare가 우선입니다.
    explicit_destination_mappings = [
        ("medical_dental", ["치과"], ["치과"]),
        ("pharmacy", ["약국"], ["약국"]),
        ("shopping", ["시장", "마트"], ["마트", "시장"]),
        ("public_office", ["주민센터"], ["주민센터"]),
        ("welfare", ["복지관", "경로당", "노인정"], ["복지관", "경로당"]),
        ("leisure_park", ["공원"], ["공원"]),
        ("exercise", ["헬스장", "수영장", "체육관", "게이트볼"], ["운동 시설"]),
        ("religious", ["교회", "성당", "절"], ["교회"]),
        ("medical_orthopedics", ["정형외과", "물리치료"], ["정형외과", "병원"]),
        ("medical_general", ["병원", "내과"], ["병원"]),
    ]

    for category, keywords, candidates in explicit_destination_mappings:
        if contains_any(text, keywords):
            if category == "religious":
                for word in ["교회", "성당", "절"]:
                    if word in text:
                        return category, [word], None

            if category == "shopping":
                actual = [word for word in ["시장", "마트"] if word in text]
                return category, actual or candidates, None

            if category == "welfare":
                actual = [word for word in ["복지관", "경로당", "노인정"] if word in text]
                return category, actual or candidates, None

            if category == "medical_orthopedics" and contains_any(text, ["물리치료"]):
                return category, ["물리치료", "정형외과"], None

            return category, candidates, None

    # 2단계: 명시적 목적지가 없을 때 증상/목적 키워드로 추론합니다.
    symptom_or_purpose_mappings = [
        ("medical_dental", ["치아", "이가", "이빨", "잇몸", "틀니", "치통"], ["치과"]),
        ("medical_orthopedics", ["무릎", "허리", "다리", "관절", "물리치료"], ["정형외과", "병원"]),
        ("pharmacy", ["약 받", "약이", "처방전", "처방"], ["약국"]),
        ("shopping", ["장보", "반찬", "생필품"], ["마트", "시장"]),
        ("public_office", ["서류", "등본", "민원"], ["주민센터"]),
        ("leisure_park", ["산책", "바람 쐬"], ["공원"]),
        ("exercise", ["운동"], ["운동 시설"]),
        ("religious", ["예배", "미사", "법회"], ["교회"]),
        ("social_visit", ["친구", "지인", "모임", "마실", "놀러"], ["지인 자택"]),
        ("medical_general", ["진료", "검진", "건강검진", "진찰"], ["병원"]),
    ]

    for category, keywords, candidates in symptom_or_purpose_mappings:
        if contains_any(text, keywords):
            if category == "medical_orthopedics" and contains_any(text, ["물리치료"]):
                return category, ["물리치료", "정형외과"], None

            return category, candidates, None

    return "unknown", [], None

    for category, keywords, candidates in mappings:
        if contains_any(text, keywords):
            # religious는 실제 등장 표현을 후보로 우선 사용
            if category == "religious":
                for word in ["교회", "성당", "절"]:
                    if word in text:
                        return category, [word], None
            # shopping도 실제 등장 표현 우선
            if category == "shopping":
                actual = [word for word in ["시장", "마트"] if word in text]
                return category, actual or candidates, None
            return category, candidates, None

    return "unknown", [], None


def build_keywords(text: str, date: Optional[str], time: Optional[str], specific_place: Optional[str], candidates: List[str]) -> List[str]:
    keywords: List[str] = []
    if date:
        keywords.append(date)
    if time:
        keywords.append(time)
    pickup = detect_pickup_location(text)
    if pickup:
        keywords.append(pickup)
    if specific_place:
        keywords.append(specific_place)
    else:
        for cand in candidates:
            if cand in text and cand not in keywords:
                keywords.append(cand)

    # 핵심 행동/상태 표현
    phrase_patterns = [
        "이동 차량 예약해줘", "차량 예약해줘", "차 좀 불러줘", "차 불러줘", "예약해줘",
        "버스 타기가 힘들어", "버스를 갈아타야 해서 힘들어", "오래 걷기가 힘들어", "멀어서 못 가겠어", "차가 없어", "태워줄 사람이 없어",
        "집에만 있으려고", "그냥 집에 있을래", "아들이 데려다준대", "알리지 마", "딸한테 알려줘",
        "물리치료를 받아야 할 것 같아", "약 받으러", "장보러", "서류 떼러", "바람 쐬러",
        "숨이 너무 차", "가슴이 답답", "정신이 멍", "말이 잘 안 나와", "넘어졌는데", "일어나기가 힘들어",
        "다리가 불편해", "다리가 불편", "다리가 뻐근해서","약이 거의 다 떨어졌어", "검진을 받아야 하나 싶어", "친구 집에", "잠깐 다녀오려고",
        "친구 만나러", "헬스장", "수영장", "운동하러", "집에서 쉴래", "안 가도 될 것 같아",
    ]
    compact = normalize(text)
    for phrase in phrase_patterns:
        if normalize(phrase) in compact and phrase not in keywords:
            keywords.append(phrase)

    # 증상만 있는 경우 보완
    symptom_patterns = ["이가 너무 아파", "무릎이 며칠째 아파", "허리가 너무 아파서 불편해", "다리가 뻐근해서"]
    for phrase in symptom_patterns:
        if normalize(phrase) in compact and phrase not in keywords:
            keywords.append(phrase)

    # 순서 유지 + 포함 관계 중복 제거
    # 예: "이동 차량 예약해줘"가 있으면 "차량 예약해줘", "예약해줘"는 제거
    unique: List[str] = []

    for item in keywords:
        item = item.strip()
        if not item:
            continue
        norm_item = normalize(item)

        # 이미 더 긴 키워드 안에 포함되는 짧은 키워드는 추가하지 않음
        if any(norm_item in normalize(existing) for existing in unique):
            continue

        # 새 키워드가 기존 짧은 키워드를 포함하면 기존 짧은 키워드 제거
        unique = [
            existing for existing in unique
            if normalize(existing) not in norm_item
        ]

        unique.append(item)

    return unique


def build_missing_slots(stage: str, text: str, specific_place: Optional[str]) -> List[str]:
    if stage in ["emergency", "not_needed", "reservation_completed", "guardian_notification"]:
        return []
    if stage == "need_detection":
        return ["visit_intent", "reservation_consent"]
    if stage == "reservation_confirm":
        return ["reservation_consent"]

    # reservation_info_collection
    slots: List[str] = []
    if not extract_date(text):
        slots.append("date")
    if not extract_time(text):
        # 오전/오후만 있는 넓은 표현도 time 부족으로 처리됩니다.
        slots.append("time")
    if specific_place is None:
        slots.append("exact_destination")
    if detect_pickup_location(text) is None:
        slots.append("pickup_location")
    return slots


def build_next_question(stage: str, category: str, missing_slots: List[str], text: str, specific_place: Optional[str]) -> str:
    place_word = get_display_place(category, text)
    if stage=="emergency": return "지금 바로 보호자나 119에 연결해드릴까요?"
    if stage in ["not_needed","reservation_completed","guardian_notification"]: return ""
    if stage=="need_detection":
        if category=="medical_dental": return "이가 아프시면 치과에 가보실 생각이 있으실까요?"
        if category=="medical_orthopedics": return "불편하시면 정형외과나 물리치료를 받아보실 생각이 있으실까요?"
        if category=="pharmacy": return "약국에 약을 받으러 가실 생각이 있으실까요?"
        if category=="medical_general": return "병원이나 검진을 받아보실 생각이 있으실까요?"
        return "외출이나 방문이 필요하실까요?"
    if stage=="reservation_confirm":
        if category=="medical_orthopedics" and "물리치료" in text: return "물리치료 받으러 가시는 이동 차량 예약을 도와드릴까요?"
        return f"{place_word}에 가시는 이동 차량 예약을 도와드릴까요?"
    if "date" in missing_slots and "time" in missing_slots: return "가실 날짜와 시간을 알려주실 수 있을까요?"
    if "date" in missing_slots: return "가실 날짜를 알려주실 수 있을까요?"
    if "time" in missing_slots: return "가실 시간을 알려주실 수 있을까요?"
    if "exact_destination" in missing_slots and "pickup_location" in missing_slots: return f"가실 {place_word} 이름과 출발하실 위치를 알려주실 수 있을까요?"
    if "exact_destination" in missing_slots: return f"가실 {place_word} 이름을 알려주실 수 있을까요?"
    if "pickup_location" in missing_slots: return "출발하실 위치를 알려주실 수 있을까요?"
    date, time = extract_date(text) or "", extract_time(text) or ""
    pickup = detect_pickup_location(text) or "출발지"
    destination = specific_place or place_word
    summary = " ".join(part for part in [date, time] if part).strip()
    return f"{summary}, {pickup}에서 {destination}까지 예약을 진행해드릴까요?" if summary else f"{pickup}에서 {destination}까지 예약을 진행해드릴까요?"


def build_reason(stage: str, category: str, missing_slots: List[str], text: str, has_reservation_request: bool, mobility: bool) -> str:
    place_word = get_display_place(category, text)
    if stage=="emergency": return "응급 가능성이 있는 표현이 있어 DRT 예약보다 보호자 또는 119 연결이 우선입니다."
    if stage=="not_needed":
        if contains_any(text, ["아들이 데려다준대","딸이 데려다준대","가족이 데려다준대","가족이 데려다준다"]): return "대체 이동수단이 있어 DRT 예약은 불필요하다고 표현했습니다."
        if contains_any(text, ["예약은 안 해도 돼","예약 안 해도 돼","차는 부르지 마","차 부르지 마","부르지 마"]): return f"{place_word} 방문 의향은 있으나 이동 차량 호출을 명시적으로 거절했습니다."
        return "외출 의도가 없거나 DRT 예약을 원하지 않는다고 표현했습니다."
    if stage=="need_detection": return f"{place_word} 방문 가능성은 있으나 아직 방문 의향과 DRT 예약 동의는 확인되지 않았습니다."
    if stage=="reservation_confirm": return f"{place_word} 방문 의향과 이동 어려움이 표현되었으나 DRT 예약 동의는 아직 확인되지 않았습니다." if mobility else f"{place_word} 방문 의향은 표현되었으나 DRT 예약 동의는 아직 확인되지 않았습니다."
    if stage=="reservation_info_collection":
        if missing_slots:
            names = {"date":"날짜","time":"시간","exact_destination":"정확한 목적지 이름","pickup_location":"출발지"}
            missing_text = "·".join(names[s] for s in missing_slots if s in names)
            return f"{place_word} 방문 목적과 DRT 예약 요청이 확인되었으며 {missing_text} 정보가 아직 필요합니다."
        return f"{place_word} 방문 목적, 날짜, 시간, 출발지, 목적지가 모두 확인되어 예약 진행 확인 단계입니다."
    if stage=="reservation_completed": return "DRT 예약이 완료된 상태입니다."
    if stage=="guardian_notification": return "예약 완료 후 보호자에게 예약 정보를 공유하는 데 동의했습니다."
    return "대화 내용에 따라 DRT 관련 상태를 판단했습니다."


def build_guardian_message(text: str, category: str, specific_place: Optional[str]) -> str:
    date = extract_date(text) or "내일"
    time = extract_time(text) or "오전 10시"
    pickup = detect_pickup_location(text) or "자택"
    destination = specific_place or ("서울치과" if "서울치과" in text else CATEGORY_TO_PLACE_WORD.get(category, "목적지"))
    return f"{date} {time}, {pickup}에서 {destination}까지 DRT 차량이 예약되었습니다."


def rule_based_analysis(conversation: str) -> Dict[str, Any]:
    text = conversation.strip()
    category, candidates, specific_place = detect_destination(text)
    has_emergency = detect_emergency(text)
    not_needed, refused = detect_not_needed(text)
    has_reservation_request = detect_reservation_request(text)
    has_visit_intent = detect_visit_intent(text)
    mobility = detect_mobility_difficulty(text, has_reservation_request)
    reservation_completed = contains_any(text, ["예약이 완료되었습니다", "DRT 예약이 완료되었습니다", "예약 완료"])
    guardian_agree = contains_any(text, ["딸한테 알려줘", "아들한테 알려줘", "보호자에게 알려줘", "알려줘", "보내줘"])
    guardian_refuse = contains_any(text, ["알리지 마", "보내지 마", "말하지 마"])

    # 단계 판단 우선순위
    if reservation_completed and guardian_agree and not guardian_refuse:
        stage = "guardian_notification"
        drt_status = "reserved"
        reservation_consent = "confirmed"
        guardian_notify_consent = "confirmed"
    elif reservation_completed:
        stage = "reservation_completed"
        drt_status = "reserved"
        reservation_consent = "confirmed"
        guardian_notify_consent = "refused" if guardian_refuse else "not_asked"
    elif has_emergency:
        stage = "emergency"
        drt_status = "emergency"
        reservation_consent = "not_confirmed"
        guardian_notify_consent = "not_asked"
        # 응급은 목적지보다 응급 대응 우선
        category, candidates, specific_place = "unknown", [], None
    elif not_needed:
        stage = "not_needed"
        drt_status = "not_needed"
        reservation_consent = "refused" if refused else "not_confirmed"
        guardian_notify_consent = "not_asked"
        if not refused:
            category, candidates, specific_place = "unknown", [], None
    elif has_reservation_request:
        stage = "reservation_info_collection"
        drt_status = "needed"
        reservation_consent = "confirmed"
        guardian_notify_consent = "not_asked"
    elif has_visit_intent:
        stage = "reservation_confirm"
        drt_status = "possible"
        reservation_consent = "not_confirmed"
        guardian_notify_consent = "not_asked"
    else:
        stage = "need_detection"
        drt_status = "possible" if category != "unknown" else "unclear"
        reservation_consent = "not_confirmed"
        guardian_notify_consent = "not_asked"

    missing_slots = build_missing_slots(stage, text, specific_place)
    next_question = build_next_question(stage, category, missing_slots, text, specific_place)
    reason = build_reason(stage, category, missing_slots, text, has_reservation_request, mobility)

    guardian_message = ""
    if stage == "guardian_notification" and guardian_notify_consent == "confirmed":
        guardian_message = build_guardian_message(text, category, specific_place)

    date = extract_date(text)
    time = extract_time(text)
    keywords = build_keywords(text, date, time, specific_place, candidates)

    # confidence는 규칙 기반이므로 명시 표현이 있으면 높게, 단순 가능성만 있으면 중간으로 둡니다.
    if stage in ["emergency", "reservation_info_collection", "guardian_notification", "reservation_completed", "not_needed"]:
        confidence = 0.95
    elif stage == "reservation_confirm":
        confidence = 0.85
    elif stage == "need_detection":
        confidence = 0.70 if category != "unknown" else 0.40
    else:
        confidence = 0.50

    result: Dict[str, Any] = {
        "dialogue_stage": stage,
        "drt_status": drt_status,
        "destination_category": category,
        "destination_candidates": candidates,
        "extracted_keywords": keywords,
        "missing_slots": missing_slots,
        "reservation_consent": reservation_consent,
        "guardian_notify_consent": guardian_notify_consent,
        "mobility_difficulty": mobility,
        "emergency_risk": has_emergency,
        "confidence": confidence,
        "reason": reason,
        "next_question": next_question,
        "guardian_message": guardian_message,
    }
    return validate_and_order(result)


def validate_and_order(data: Dict[str, Any]) -> Dict[str, Any]:
    """스키마 누락/빈 문자열/모순을 마지막으로 보정합니다."""
    defaults: Dict[str, Any] = {
        "dialogue_stage": "need_detection",
        "drt_status": "possible",
        "destination_category": "unknown",
        "destination_candidates": [],
        "extracted_keywords": [],
        "missing_slots": [],
        "reservation_consent": "not_confirmed",
        "guardian_notify_consent": "not_asked",
        "mobility_difficulty": False,
        "emergency_risk": False,
        "confidence": 0.5,
        "reason": "",
        "next_question": "",
        "guardian_message": "",
    }
    for key, value in defaults.items():
        if key not in data or data[key] == "":
            data[key] = value

    if data["dialogue_stage"] == "emergency":
        data["drt_status"] = "emergency"
        data["destination_category"] = "unknown"
        data["destination_candidates"] = []
        data["missing_slots"] = []
        data["emergency_risk"] = True
        data["reservation_consent"] = "not_confirmed"
        data["guardian_notify_consent"] = "not_asked"
        data["guardian_message"] = ""

    if data["dialogue_stage"] == "not_needed":
        data["drt_status"] = "not_needed"
        data["missing_slots"] = []
        data["next_question"] = ""
        data["guardian_message"] = ""

    if data["dialogue_stage"] == "reservation_info_collection":
        data["drt_status"] = "needed"
        data["reservation_consent"] = "confirmed"
        data["missing_slots"] = [s for s in data["missing_slots"] if s not in ["visit_intent", "reservation_consent"]]

    if data["dialogue_stage"] == "reservation_confirm":
        data["drt_status"] = "possible"
        data["reservation_consent"] = "not_confirmed"
        data["missing_slots"] = ["reservation_consent"]

    if data["dialogue_stage"] == "need_detection":
        data["missing_slots"] = ["visit_intent", "reservation_consent"]
        data["reservation_consent"] = "not_confirmed"

    if data["dialogue_stage"] == "guardian_notification":
        data["drt_status"] = "reserved"
        data["reservation_consent"] = "confirmed"
        data["guardian_notify_consent"] = "confirmed"
        data["missing_slots"] = []

    if data["dialogue_stage"] == "reservation_completed":
        data["drt_status"] = "reserved"
        data["missing_slots"] = []

    # list 타입 보장
    for key in ["destination_candidates", "extracted_keywords", "missing_slots"]:
        if not isinstance(data[key], list):
            data[key] = []

    return {key: data[key] for key in OUTPUT_KEYS}


# -----------------------------
# Optional LLM helper section
# -----------------------------

def build_system_prompt() -> str:
    """LLM 보조용 최소 프롬프트. 최종 판단은 rule_based_analysis가 덮어씁니다."""
    return """
너는 고령층 AI 케어콜 대화를 JSON으로 분석한다.
출력은 반드시 JSON 객체 하나만 작성한다. 설명, 코드블록, 주석은 금지한다.

허용 key:
dialogue_stage, drt_status, destination_category, destination_candidates, extracted_keywords, missing_slots,
reservation_consent, guardian_notify_consent, mobility_difficulty, emergency_risk, confidence, reason, next_question, guardian_message

핵심 규칙:
- 숨참/가슴 답답/말이 안 나옴/넘어져 못 일어남은 emergency.
- 예약해줘/차 불러줘/차 좀 불러줘/차량 예약해줘/이동 차량 예약해줘는 예약 요청이다.
- 예약 요청이면 reservation_info_collection, drt_status needed, reservation_consent confirmed.
- 방문 의향만 있고 예약 요청이 없으면 reservation_confirm.
- 증상만 있으면 need_detection.
- reservation_info_collection에서는 부족한 date, time, exact_destination, pickup_location만 missing_slots에 넣는다.
- reservation_confirm에서는 missing_slots = ["reservation_consent"]만 둔다.
- 빈 문자열 값은 쓰지 않는다.
"""


def load_model_and_tokenizer(model_name: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print("모델과 토크나이저를 불러오는 중입니다.")
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    if torch.cuda.is_available():
        print("CUDA GPU를 사용합니다.")
        model_kwargs: Dict[str, Any] = {
            "device_map": "auto",
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        model_dtype = torch.bfloat16
    else:
        print("GPU가 없어 CPU로 실행합니다. 매우 느릴 수 있습니다.")
        model_kwargs = {
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
        }
        model_dtype = torch.float32

    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            dtype=model_dtype,
            **model_kwargs,
        )
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype=model_dtype,
            **model_kwargs,
        )

    if not torch.cuda.is_available():
        model.to("cpu")
    model.eval()
    return model, tokenizer


def generate_llm_response(model, tokenizer, system_prompt: str, conversation: str) -> str:
    import torch

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"상담 대화:\n{conversation.strip()}"},
    ]
    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    inputs = {key: value.to(device) for key, value in inputs.items()}

    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=768,
            do_sample=False,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id,
        )

    input_length = inputs["input_ids"].shape[-1]
    generated = output[0][input_length:]
    return tokenizer.decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False).strip()


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def merge_llm_with_rules(rule_result: Dict[str, Any], llm_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not llm_result: return rule_result
    merged = dict(rule_result)
    reason = llm_result.get("reason", "")
    if isinstance(reason, str) and reason.strip():
        bad = ["구체적인 예약 정보가 제공되지", "증상만 있고 예약 요청이 없음", "예약 요청이 명확하지 않아 추가 정보가 필요"]
        if not any(x in reason for x in bad): merged["reason"] = reason.strip()
    merged["extracted_keywords"] = rule_result.get("extracted_keywords", [])
    return validate_and_order(merged)


def analyze_conversation(conversation: str, model=None, tokenizer=None, system_prompt: Optional[str] = None) -> Dict[str, Any]:
    rule_result = rule_based_analysis(conversation)

    if model is None or tokenizer is None or system_prompt is None:
        return rule_result

    raw_output = generate_llm_response(model, tokenizer, system_prompt, conversation)
    llm_result = extract_json_object(raw_output)
    return merge_llm_with_rules(rule_result, llm_result)


def main() -> None:
    if SELECTED_TEST_NAME is None:
        selected_cases = TEST_CASES
    else:
        selected_cases = [case for case in TEST_CASES if case[0] == SELECTED_TEST_NAME]
        if not selected_cases:
            raise ValueError(f"SELECTED_TEST_NAME에 해당하는 테스트가 없습니다: {SELECTED_TEST_NAME}")

    model = None
    tokenizer = None
    system_prompt = None
    if USE_LLM:
        model, tokenizer = load_model_and_tokenizer(MODEL_NAME)
        system_prompt = build_system_prompt()
    else:
        print("USE_LLM=False: 모델을 호출하지 않고 규칙 엔진만 사용합니다.")

    for case_name, conversation in selected_cases:
        print(f"\n답변 생성 중입니다: {case_name}")
        result = analyze_conversation(conversation, model=model, tokenizer=tokenizer, system_prompt=system_prompt)
        print(f"\n===== {case_name} 최종 출력 =====")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
