"""통화 한 건의 대화 상태를 기억하는 상태 기계.

## 왜 필요한가

케어콜 분석기(`care_call_bot/drt_analyzer.py`)는 **넘겨준 텍스트 전체**를 매번 다시
해석한다. 데모 코드가 대화를 통째로 이어 붙여 넘기다 보니
(`chat_demo.py:249`, `gemini_chat_demo.py:140`), 어르신이 한 번이라도
"오늘은 집에 있을래"라고 하시면 그 표현이 텍스트에 계속 남아

    detect_not_needed() -> True
      -> drt_analyzer.py:563  reservation_request 를 강제로 False
      -> drt_analyzer.py:629  not_needed 가 다른 판정보다 먼저 반환

이 되어 **그 통화에서는 다시 예약할 수 없다.** 뒤늦게 "역시 병원 가야겠어"라고
하셔도 앞 문장이 계속 이기기 때문이다.

## 어떻게 푸는가

분석기에는 **최신 발화 한 마디만** 넘기고, 누적은 이 상태 기계가 맡는다.
턴마다 나온 사실을 규칙에 따라 병합하므로 나중 발화가 앞선 발화를 뒤집을 수 있다.

    발화 → 분석기(최신 한 마디) → 턴 사실 → 상태 병합 → 분석기 형태로 재구성 → 브릿지

마지막에 분석기 출력과 **같은 모양**으로 되돌리기 때문에 브릿지는 고칠 필요가 없다.
분석기도 고치지 않는다(팀원 담당 파트라 건드리지 않는 편이 낫다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# 분석기의 dialogue_stage 값과 같은 문자열을 쓴다. 브릿지가 이 값으로 판단하기 때문이다.
STAGE_EMERGENCY = "emergency"
STAGE_NOT_NEEDED = "not_needed"
STAGE_NEED_DETECTION = "need_detection"
STAGE_RESERVATION_CONFIRM = "reservation_confirm"
STAGE_RESERVATION_INFO = "reservation_info_collection"
STAGE_RESERVATION_COMPLETED = "reservation_completed"
STAGE_GUARDIAN_NOTIFICATION = "guardian_notification"

# 목적지 관련 필드는 한 묶음으로 움직인다. 카테고리만 남고 검색어가 옛것이면
# 엉뚱한 곳을 찾게 되므로, 이어받을 때도 버릴 때도 통째로 다룬다.
_DESTINATION_FIELDS = (
    "destination_category",
    "destination_candidates",
    "search_keywords",
    "search_mode",
    "sk_category",
    "place_resolution_required",
    "place_resolution_method",
    "place_resolution_question",
    "medical_department_candidates",
    "medical_clarification_required",
    "medical_clarification_question",
)

# 목적지가 확정되지 않았음을 뜻하는 슬롯. 브릿지의 BLOCKING_SLOTS와 같은 의미다.
_DESTINATION_SLOTS = ("medical_department", "place_resolution_method", "exact_destination")
# 예약에 필요하지만 목적지 확정을 막지는 않는 슬롯.
_INFO_SLOTS = ("date", "time", "pickup_location")


def _as_str(value: Any, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


@dataclass(frozen=True, slots=True)
class TurnFacts:
    """발화 한 마디에서 뽑아낸 사실. 분석기 출력을 그대로 옮겨 담는다."""

    emergency: bool = False
    outing_refused: bool = False       # "집에 있을래", "차는 안 불러도 돼"
    visit_intent: bool = False         # "병원 가야 해"
    reservation_signal: str = ""       # confirmed | refused | "" (신호 없음)
    guardian_signal: str = ""          # confirmed | refused | "" (신호 없음)
    mobility_difficulty: bool = False
    destination: dict[str, Any] = field(default_factory=dict)  # 목적지 블록(있을 때만)
    filled_slots: set[str] = field(default_factory=set)        # 이번 턴에 채워진 슬롯
    keywords: list[str] = field(default_factory=list)
    next_question: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_analyzer_output(cls, payload: dict[str, Any]) -> "TurnFacts":
        """분석기가 **한 마디**를 보고 돌려준 결과를 사실로 정리한다."""
        stage = _as_str(payload.get("dialogue_stage"))
        consent = _as_str(payload.get("reservation_consent"))
        missing = set(_as_list(payload.get("missing_slots")))

        # 목적지를 알아냈을 때만 블록을 만든다. unknown이면 이전 것을 유지해야 한다.
        destination: dict[str, Any] = {}
        if _as_str(payload.get("destination_category"), "unknown") != "unknown":
            destination = {key: payload.get(key) for key in _DESTINATION_FIELDS}
            # 목적지와 함께 온 미확정 슬롯도 같이 들고 간다.
            destination["_pending_slots"] = sorted(missing & set(_DESTINATION_SLOTS))

        # 분석기는 신호가 없을 때도 not_confirmed를 준다. 그건 "모름"이지 "거절"이 아니다.
        reservation_signal = consent if consent in {"confirmed", "refused"} else ""
        guardian = _as_str(payload.get("guardian_notify_consent"))
        guardian_signal = guardian if guardian in {"confirmed", "refused"} else ""

        # 이번 턴에 채워진 정보 슬롯 = 정보 슬롯 중 missing에 없는 것
        filled = {slot for slot in _INFO_SLOTS if slot not in missing}
        # need_detection 단계는 슬롯 판정 자체를 하지 않으므로 채워졌다고 볼 수 없다.
        if stage == STAGE_NEED_DETECTION:
            filled = set()

        return cls(
            emergency=bool(payload.get("emergency_risk")) or stage == STAGE_EMERGENCY,
            outing_refused=stage == STAGE_NOT_NEEDED or consent == "refused",
            visit_intent=stage in {STAGE_RESERVATION_CONFIRM, STAGE_RESERVATION_INFO},
            reservation_signal=reservation_signal,
            guardian_signal=guardian_signal,
            mobility_difficulty=bool(payload.get("mobility_difficulty")),
            destination=destination,
            filled_slots=filled,
            keywords=_as_list(payload.get("extracted_keywords")),
            next_question=_as_str(payload.get("next_question")),
            raw=dict(payload),
        )


@dataclass
class ConversationState:
    """통화 한 건 동안 쌓이는 상태."""

    session_id: str
    user_id: str
    turn_count: int = 0

    # 안전 관련은 한 번 켜지면 자동으로 꺼지지 않는다.
    escalated: bool = False
    # 외출 거절은 **뒤집을 수 있다.** 이 통화의 결함을 고치는 핵심 지점이다.
    outing_refused: bool = False
    visit_intent: bool = False
    reservation_consent: str = "not_confirmed"   # confirmed | refused | not_confirmed
    guardian_notify_consent: str = "not_asked"   # confirmed | refused | not_asked
    mobility_difficulty: bool = False
    reserved: bool = False                       # 배차가 확정된 뒤 True

    destination: dict[str, Any] = field(default_factory=dict)
    filled_slots: set[str] = field(default_factory=set)
    keywords: list[str] = field(default_factory=list)
    last_question: str = ""

    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    # ── 병합 ────────────────────────────────────────────────────────────

    def apply(self, facts: TurnFacts) -> None:
        """한 턴의 사실을 상태에 반영한다. **나중 발화가 앞선 발화를 이긴다.**"""
        self.turn_count += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.last_question = facts.next_question

        # 1) 응급은 한 번 감지되면 유지한다. 통화 중 저절로 해제하지 않는다.
        if facts.emergency:
            self.escalated = True

        # 2) 방문 의향·예약 요청이 새로 나오면 앞선 거절을 취소한다.
        #    ★ 이것이 "집에 있을래" 한 번에 통화 내내 막히던 문제의 해소 지점이다.
        if facts.visit_intent or facts.reservation_signal == "confirmed":
            self.outing_refused = False
            self.visit_intent = True
        elif facts.outing_refused:
            self.outing_refused = True
            self.visit_intent = False

        # 3) 예약 동의는 명시 신호가 있을 때만 바꾼다. 신호가 없으면 이전 값을 지킨다.
        if facts.reservation_signal:
            self.reservation_consent = facts.reservation_signal
        if facts.guardian_signal:
            self.guardian_notify_consent = facts.guardian_signal

        # 4) 목적지는 새로 말씀하시면 통째로 교체하고, 아니면 앞서 정한 것을 이어간다.
        if facts.destination:
            self.destination = dict(facts.destination)
        elif self.outing_refused:
            # 외출을 접으셨으면 목적지도 함께 비운다. 나중에 마음을 바꾸시면 다시 말씀하신다.
            self.destination = {}

        # 5) 한 번 채워진 정보 슬롯은 유지한다(날짜·시간·출발지).
        self.filled_slots |= facts.filled_slots
        if not self.destination:
            self.filled_slots -= set(_DESTINATION_SLOTS)

        if facts.mobility_difficulty:
            self.mobility_difficulty = True

        for keyword in facts.keywords:
            if keyword not in self.keywords:
                self.keywords.append(keyword)

    def mark_reserved(self) -> None:
        self.reserved = True
        self.reservation_consent = "confirmed"

    # ── 단계 판정 ────────────────────────────────────────────────────────

    @property
    def stage(self) -> str:
        """쌓인 상태로 대화 단계를 다시 계산한다.

        분석기가 한 마디만 보고 매긴 단계는 맥락이 없으므로 그대로 쓰지 않는다.
        """
        if self.escalated:
            return STAGE_EMERGENCY
        if self.reserved:
            if self.guardian_notify_consent == "confirmed":
                return STAGE_GUARDIAN_NOTIFICATION
            return STAGE_RESERVATION_COMPLETED
        if self.outing_refused:
            return STAGE_NOT_NEEDED
        if self.reservation_consent == "confirmed":
            return STAGE_RESERVATION_INFO
        if self.visit_intent:
            return STAGE_RESERVATION_CONFIRM
        return STAGE_NEED_DETECTION

    @property
    def drt_status(self) -> str:
        return {
            STAGE_EMERGENCY: "emergency",
            STAGE_NOT_NEEDED: "not_needed",
            STAGE_RESERVATION_INFO: "needed",
            STAGE_RESERVATION_CONFIRM: "possible",
            STAGE_RESERVATION_COMPLETED: "reserved",
            STAGE_GUARDIAN_NOTIFICATION: "reserved",
        }.get(self.stage, "possible" if self.destination else "unclear")

    # ── 브릿지에 넘길 형태로 되돌리기 ────────────────────────────────────

    def to_analyzer_output(self) -> dict[str, Any]:
        """분석기 출력과 **같은 모양**의 dict를 만든다.

        브릿지(`bridge/contract.py`)가 이 모양을 계약으로 삼기 때문에, 여기서 맞춰
        주면 브릿지를 한 줄도 고치지 않고 상태 기계를 끼워 넣을 수 있다.
        """
        stage = self.stage
        destination = dict(self.destination)
        pending = list(destination.pop("_pending_slots", []) or [])

        if stage in {STAGE_EMERGENCY, STAGE_NOT_NEEDED,
                     STAGE_RESERVATION_COMPLETED, STAGE_GUARDIAN_NOTIFICATION}:
            missing: list[str] = []
        elif stage == STAGE_NEED_DETECTION:
            missing = ["visit_intent", "reservation_consent"]
        else:
            missing = list(pending)
            if stage == STAGE_RESERVATION_CONFIRM:
                missing.append("reservation_consent")
            else:
                missing += [slot for slot in _INFO_SLOTS if slot not in self.filled_slots]

        # 분석기의 next_question은 **그 한 마디만 보고** 만든 질문이라 병합 상태와
        # 어긋날 수 있다. 목적지가 아직 안 정해졌는데 "날짜를 알려주세요"를 묻는 식이다.
        # 그때만 비워서, 브릿지가 목적지 확정 질문(place_resolution_question)을 쓰게 한다.
        # 동의를 묻는 단계(reservation_confirm)에서는 분석기 질문이 맞으므로 그대로 둔다.
        next_question = self.last_question
        if pending and stage == STAGE_RESERVATION_INFO:
            next_question = ""

        output: dict[str, Any] = {
            "dialogue_stage": stage,
            "drt_status": self.drt_status,
            "destination_category": "unknown",
            "destination_candidates": [],
            "search_keywords": [],
            "search_mode": "not_applicable",
            "place_resolution_required": False,
            "place_resolution_question": "",
            "missing_slots": missing,
            "reservation_consent": self.reservation_consent,
            "guardian_notify_consent": self.guardian_notify_consent,
            "mobility_difficulty": self.mobility_difficulty,
            "emergency_risk": self.escalated,
            "extracted_keywords": list(self.keywords),
            "next_question": next_question,
        }
        # 응급이거나 외출을 접으신 상태에서는 목적지를 실어 보내지 않는다.
        if destination and stage not in {STAGE_EMERGENCY, STAGE_NOT_NEEDED}:
            output.update({key: value for key, value in destination.items() if value is not None})
        return output

    def snapshot(self) -> dict[str, Any]:
        """디버깅·화면 표시용 요약."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turn_count": self.turn_count,
            "stage": self.stage,
            "drt_status": self.drt_status,
            "destination": self.destination.get("destination_category", "unknown"),
            "reservation_consent": self.reservation_consent,
            "outing_refused": self.outing_refused,
            "escalated": self.escalated,
            "reserved": self.reserved,
            "filled_slots": sorted(self.filled_slots),
            "updated_at": self.updated_at,
        }


class ConversationStore:
    """통화 세션 보관소. 지금은 메모리이고, 실제 서비스에서는 Redis 등으로 바뀐다."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationState] = {}

    def create(self, session_id: str, user_id: str) -> ConversationState:
        state = ConversationState(session_id=session_id, user_id=user_id)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str) -> ConversationState | None:
        return self._sessions.get(session_id)

    def end(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def active_count(self) -> int:
        return len(self._sessions)
