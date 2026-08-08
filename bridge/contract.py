"""케어콜 분석 결과(care-call-bot의 `drt_analyzer.analyze_conversation()` 출력)를
브릿지가 다루는 표준 형태로 옮긴다.

care-call-bot의 코드를 import하지 않는다. 그쪽은 torch/Gemini/faster-whisper 의존성과
macOS 전용 TTS 코드가 섞여 있어서, 브릿지는 **출력 JSON만**을 계약으로 삼는다.
그래서 필드가 빠지거나(구버전 v4.py 출력) 늘어나도 죽지 않고 기본값으로 흡수한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# DRT 호출을 진행할 수 없는 대화 단계들. drt_analyzer.py의 dialogue_stage 값과 같다.
STAGE_EMERGENCY = "emergency"
STAGE_NOT_NEEDED = "not_needed"
STAGE_NEED_DETECTION = "need_detection"
STAGE_RESERVATION_CONFIRM = "reservation_confirm"
STAGE_RESERVATION_INFO = "reservation_info_collection"
STAGE_RESERVATION_COMPLETED = "reservation_completed"
STAGE_GUARDIAN_NOTIFICATION = "guardian_notification"

# 목적지가 아직 한 곳으로 좁혀지지 않아 DRT 검색어를 만들 수 없는 search_mode들.
UNRESOLVED_SEARCH_MODES = {
    "ask_frequent_or_nearby",
    "ask_exact_place_name",
    "direct_address_required",
    "not_applicable",
    "",
}

# 이 슬롯들이 비어 있으면 목적지 자체가 확정되지 않은 것이므로 DRT를 호출하지 않는다.
# date/time/pickup_location/*_full_address는 여기 넣지 않는다 — 이유는 gate.py 참고.
BLOCKING_SLOTS = ("medical_department", "place_resolution_method", "exact_destination")

# 정확명(고유명사) 복원용. care-call-bot의 PLACE_SUFFIXES/GENERIC_PLACES와 같은 목록을
# 의도적으로 복제해 둔다. 그쪽을 import하지 않는다는 원칙 때문이며, 목록이 갱신되면
# 여기도 같이 손봐야 한다(docs/integration_design.md의 '알려진 갭' 참고).
PLACE_SUFFIXES = (
    "치과", "정형외과", "피부과", "내과", "신경과", "안과", "이비인후과", "재활의학과",
    "병원", "의원", "약국",
    "시장", "마트", "편의점",
    "주민센터", "행정복지센터", "구청", "시청", "군청", "은행",
    "복지관", "경로당", "노인정",
    "공원", "문화센터", "도서관",
    "교회", "성당", "절",
    "헬스장", "수영장", "체육관",
)

GENERIC_PLACES = frozenset(PLACE_SUFFIXES)


def recover_specific_place(extracted_keywords: list[str]) -> str | None:
    """`extracted_keywords`에서 고유명사형 목적지명을 복원한다.

    drt_analyzer.py는 내부적으로 `specific_place`("중앙도서관")를 계산하지만
    OUTPUT_KEYS에 넣지 않아 출력 JSON에서 사라진다. 그런데 `extracted_keywords`에는
    남아 있으므로 거기서 되살린다. 상위(care-call-bot)에서 specific_place를
    출력에 추가하면 이 복원은 불필요해진다.
    """
    for keyword in extracted_keywords:
        text = re.sub(r"[^가-힣A-Za-z0-9]", "", str(keyword or ""))
        if not text or text in GENERIC_PLACES:
            continue
        for suffix in PLACE_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                return text
    return None


def _as_str(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _as_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


@dataclass(frozen=True, slots=True)
class CareCallResult:
    """분석기 출력 중 브릿지가 실제로 쓰는 필드만 추린 표준 형태."""

    dialogue_stage: str = STAGE_NEED_DETECTION
    drt_status: str = "unclear"
    destination_category: str = "unknown"
    destination_candidates: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)
    search_mode: str = ""
    place_resolution_required: bool = False
    place_resolution_question: str = ""
    missing_slots: list[str] = field(default_factory=list)
    reservation_consent: str = "not_confirmed"
    guardian_notify_consent: str = "not_asked"
    emergency_risk: bool = False
    mobility_difficulty: bool = False
    next_question: str = ""
    extracted_keywords: list[str] = field(default_factory=list)
    origin_full_address: str = ""
    destination_full_address: str = ""
    # 분석기가 직접 주면 그 값을 쓰고, 없으면 extracted_keywords에서 복원한다.
    specific_place: str = ""
    # 정규화 과정에서 원본을 잃지 않도록 통째로 보관한다(감사 로그용).
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_analyzer_output(cls, payload: dict[str, Any]) -> "CareCallResult":
        if not isinstance(payload, dict):
            raise TypeError("분석 결과는 JSON 객체여야 합니다.")

        extracted_keywords = _as_str_list(payload.get("extracted_keywords"))
        specific_place = _as_str(payload.get("specific_place"))
        if not specific_place:
            specific_place = recover_specific_place(extracted_keywords) or ""

        return cls(
            dialogue_stage=_as_str(payload.get("dialogue_stage"), STAGE_NEED_DETECTION),
            drt_status=_as_str(payload.get("drt_status"), "unclear"),
            destination_category=_as_str(payload.get("destination_category"), "unknown"),
            destination_candidates=_as_str_list(payload.get("destination_candidates")),
            search_keywords=_as_str_list(payload.get("search_keywords")),
            search_mode=_as_str(payload.get("search_mode")),
            place_resolution_required=_as_bool(payload.get("place_resolution_required")),
            place_resolution_question=_as_str(payload.get("place_resolution_question")),
            missing_slots=_as_str_list(payload.get("missing_slots")),
            reservation_consent=_as_str(payload.get("reservation_consent"), "not_confirmed"),
            guardian_notify_consent=_as_str(payload.get("guardian_notify_consent"), "not_asked"),
            emergency_risk=_as_bool(payload.get("emergency_risk")),
            mobility_difficulty=_as_bool(payload.get("mobility_difficulty")),
            next_question=_as_str(payload.get("next_question")),
            extracted_keywords=extracted_keywords,
            origin_full_address=_as_str(payload.get("origin_full_address")),
            destination_full_address=_as_str(payload.get("destination_full_address")),
            specific_place=specific_place,
            raw=dict(payload),
        )

    @property
    def blocking_slots(self) -> list[str]:
        """목적지 확정 자체를 막는 슬롯만 추린다."""
        return [slot for slot in self.missing_slots if slot in BLOCKING_SLOTS]

    @property
    def has_schedule_hint(self) -> bool:
        """어르신이 날짜나 시간을 이미 말씀하셨는지.

        분석기 출력에는 날짜·시간 값이 따로 담기지 않고 missing_slots에 "date"/"time"이
        빠져 있는지로만 알 수 있다. drt_service는 예약 시각을 받지 않는 즉시 호출
        모델이라, 이 신호가 있으면 경고로 남긴다(gate.py 참고).
        """
        if self.dialogue_stage != STAGE_RESERVATION_INFO:
            return False
        return "date" not in self.missing_slots or "time" not in self.missing_slots
