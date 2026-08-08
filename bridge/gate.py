"""DRT 서비스를 호출해도 되는 상태인지 판정하는 게이트.

여기서 막지 않으면 응급 상황이나 "예약 안 할래"라는 발화에도 배차 API가 불려 나간다.
brige의 모든 DRT 호출은 반드시 이 게이트를 먼저 통과해야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bridge.contract import (
    STAGE_EMERGENCY,
    STAGE_GUARDIAN_NOTIFICATION,
    STAGE_NEED_DETECTION,
    STAGE_NOT_NEEDED,
    STAGE_RESERVATION_COMPLETED,
    STAGE_RESERVATION_CONFIRM,
    STAGE_RESERVATION_INFO,
    CareCallResult,
)

# 게이트가 내리는 결정.
ACTION_CALL_DRT = "call_drt"
ACTION_ASK_USER = "ask_user"
ACTION_ESCALATE = "escalate_emergency"
ACTION_NOTIFY_GUARDIAN = "notify_guardian"
ACTION_SKIP = "skip"

_EMERGENCY_SPEECH = "많이 놀라셨겠어요. 제가 지금 바로 보호자분과 구급대에 연락드릴게요."


@dataclass(frozen=True, slots=True)
class GateDecision:
    action: str
    code: str
    spoken: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def should_call_drt(self) -> bool:
        return self.action == ACTION_CALL_DRT


def evaluate(result: CareCallResult) -> GateDecision:
    """분석 결과 하나를 보고 DRT 호출 여부를 정한다."""
    notes: list[str] = []

    # 1) 응급이 가장 우선. 목적지나 예약 동의가 무엇이든 배차보다 구조가 먼저다.
    if result.emergency_risk or result.dialogue_stage == STAGE_EMERGENCY:
        return GateDecision(ACTION_ESCALATE, "emergency_detected", _EMERGENCY_SPEECH)

    # 2) 외출 의사가 없거나 차량 호출을 거절한 경우.
    if result.dialogue_stage == STAGE_NOT_NEEDED or result.reservation_consent == "refused":
        return GateDecision(ACTION_SKIP, "reservation_not_wanted")

    # 3) 이미 예약이 끝난 대화. 보호자 통보 동의가 있으면 통보만 처리한다.
    if result.dialogue_stage == STAGE_GUARDIAN_NOTIFICATION:
        return GateDecision(ACTION_NOTIFY_GUARDIAN, "guardian_notification_requested")
    if result.dialogue_stage == STAGE_RESERVATION_COMPLETED:
        return GateDecision(ACTION_SKIP, "already_reserved")

    # 4) 아직 방문 의향조차 확인되지 않은 단계. 분석기가 만든 질문을 그대로 이어서 묻는다.
    if result.dialogue_stage == STAGE_NEED_DETECTION:
        return GateDecision(ACTION_ASK_USER, "visit_intent_unknown", result.next_question)

    # 5) 방문 의향은 있으나 차량 호출 동의가 아직 없는 단계.
    #    여기서 미리 /api/plan을 부르면 동의 없이 TMAP 쿼터를 쓰게 되므로 부르지 않는다.
    if result.dialogue_stage == STAGE_RESERVATION_CONFIRM:
        return GateDecision(ACTION_ASK_USER, "reservation_consent_pending", result.next_question)

    # 6) 정보 수집 단계.
    if result.dialogue_stage == STAGE_RESERVATION_INFO:
        if result.reservation_consent != "confirmed":
            return GateDecision(ACTION_ASK_USER, "reservation_consent_pending", result.next_question)

        blocking = result.blocking_slots
        if blocking:
            # 진료과나 목적지가 안 정해졌으면 검색어를 만들 수 없다.
            question = result.next_question or result.place_resolution_question
            return GateDecision(
                ACTION_ASK_USER, f"missing:{','.join(blocking)}", question, notes=notes
            )

        # 날짜·시간은 DRT 호출을 막지 않는다. drt_service는 예약 시각을 받지 않는
        # "지금 부르는" 모델이라 date/time 슬롯을 쓸 곳이 없기 때문이다. 다만 어르신이
        # 이미 시각을 말씀하셨다면 그대로 즉시 배차하면 안 되므로 경고를 남긴다.
        if result.has_schedule_hint:
            notes.append("schedule_hint_present")
        # 출발지·도착지 전체 주소도 막지 않는다. 브릿지는 텍스트 주소 대신
        # 등록 좌표(location.py)를 쓰기 때문이다.
        if "origin_full_address" in result.missing_slots:
            notes.append("origin_address_unresolved_uses_profile")

        return GateDecision(ACTION_CALL_DRT, "ready", notes=notes)

    return GateDecision(ACTION_SKIP, f"unhandled_stage:{result.dialogue_stage}")
