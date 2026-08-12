"""다솜이 케어콜과 DRT 분석/백엔드를 연결하는 단일 오케스트레이터."""

from __future__ import annotations

import copy
from typing import Protocol, Sequence

from .analyzer import DRTAnalyzer, is_affirmative, is_negative
from .backend import (
    DRTBackendClient,
    DRTBackendError,
    interpret_plan,
    interpret_reservation,
)
from .responses import RuleCareResponder, compose_reply
from .schemas import DRTAnalysis, JointLLMResult, SessionState, TurnResult


class CareResponder(Protocol):
    def respond(
        self,
        history: Sequence[dict[str, str]],
        user_text: str,
        *,
        drt_candidate: bool,
        analysis_hint: DRTAnalysis | None,
        state: SessionState,
    ) -> JointLLMResult: ...


class CareCallDRTOrchestrator:
    """한 턴당 하나의 일관된 답변과 DRT 상태를 만든다.

    Gemini 대화 모드에서는 ``GeminiJointResponder``가 답변+의미를 한 번에 반환하므로
    같은 턴에 별도 Gemini 분석을 다시 호출하지 않는다. Mi:dm 모드에서는 로컬 답변과
    선택적 Gemini 의미 보강을 조합할 수 있다.
    """

    def __init__(
        self,
        *,
        analyzer: DRTAnalyzer | None = None,
        responder: CareResponder | None = None,
        backend: DRTBackendClient | None = None,
    ) -> None:
        self.analyzer = analyzer or DRTAnalyzer()
        self.responder = responder or RuleCareResponder()
        self.backend = backend

    @staticmethod
    def _drt_context_active(state: SessionState, pre_semantic: object) -> bool:
        return bool(
            getattr(pre_semantic, "emergency_risk", False)
            or getattr(pre_semantic, "reservation_request", False)
            or getattr(pre_semantic, "visit_intent", False)
            or getattr(pre_semantic, "destination_category", "unknown") != "unknown"
            or state.destination_category != "unknown"
            or state.last_target_slot is not None
        )

    def _pending_route_turn(self, user_text: str, state: SessionState) -> TurnResult | None:
        if state.pending_plan is None:
            return None

        analysis = state.last_analysis
        if analysis is None:
            analysis = self.analyzer.analyze_turn(user_text, state, allow_internal_gemini=False)

        if is_affirmative(user_text):
            if self.backend is None or state.pending_plan_request is None:
                return TurnResult(
                    assistant_reply="경로는 확인됐지만 예약 서버 연결이 꺼져 있어 실제 호출은 진행하지 못했습니다.",
                    analysis=analysis,
                    plan=state.pending_plan,
                    backend_error="DRT backend disabled",
                )
            try:
                reservation = self.backend.create_reservation(state.pending_plan_request)
                state.pending_reservation = reservation
                state.pending_plan = None
                state.pending_plan_request = None
                return TurnResult(
                    assistant_reply=interpret_reservation(reservation),
                    analysis=analysis,
                    plan=reservation,
                )
            except DRTBackendError as exc:
                return TurnResult(
                    assistant_reply="예약 서버 연결이 원활하지 않아 호출을 완료하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
                    analysis=analysis,
                    plan=state.pending_plan,
                    backend_error=str(exc),
                )

        if is_negative(user_text):
            state.pending_plan = None
            state.pending_plan_request = None
            return TurnResult(
                assistant_reply="알겠습니다. 이 경로로는 예약하지 않을게요.",
                analysis=analysis,
            )

        interpretation = interpret_plan(state.pending_plan)
        return TurnResult(
            assistant_reply=f"예약 여부를 확인할게요. {interpretation.message}",
            analysis=analysis,
            plan=state.pending_plan,
        )

    def process_turn(
        self,
        user_text: str,
        state: SessionState,
        history: Sequence[dict[str, str]] = (),
        *,
        weather: str | None = None,
        speed_level: str | None = None,
    ) -> TurnResult:
        pending = self._pending_route_turn(user_text, state)
        if pending is not None:
            return pending

        pre_semantic, _ = self.analyzer.precheck(user_text, state)
        drt_candidate = self._drt_context_active(state, pre_semantic)

        # 실제 state를 두 번 갱신하지 않도록 복사본에서 규칙 힌트만 계산한다.
        hint_state = copy.deepcopy(state)
        hint = self.analyzer.analyze_turn(
            user_text,
            hint_state,
            allow_internal_gemini=False,
        )

        joint = self.responder.respond(
            history,
            user_text,
            drt_candidate=drt_candidate,
            analysis_hint=hint,
            state=state,
        )

        analysis = self.analyzer.analyze_turn(
            user_text,
            state,
            llm_semantic=joint.semantic,
            # Gemini joint 호출을 이미 시도한 턴에는 두 번째 API 호출 금지.
            allow_internal_gemini=not joint.semantic_call_attempted,
        )
        reply = compose_reply(joint.assistant_reply, analysis)
        plan: dict | None = None
        backend_error: str | None = None

        # 모든 예약 슬롯을 모은 뒤 계획을 한 번 계산하고, 실제 예약 전 최종 경로 확인.
        # state.pending_reservation is None 조건이 원래 빠져 있었다 — 예약이 이미
        # 완료된 뒤에도 슬롯(목적지/날짜/시간/픽업)이 SessionState에 그대로 남아
        # 있어 ready_for_reservation이 계속 True였다. 그래서 예약 성공 후 아무
        # 발화("고마워" 같은 인사조차)에 대해서도 매번 같은 경로를 다시 계획하고,
        # 그 답이 우연히 긍정으로 들리면(예: "응," "진행해 줘") 차량이 한 번 더
        # 배차되는 실제 이중 배차 버그가 났다(2026-08-12 실제 통화에서 재현).
        if (
            analysis.ready_for_reservation
            and self.backend is not None
            and state.pending_plan is None
            and state.pending_reservation is None
        ):
            try:
                plan, request = self.backend.plan(
                    analysis,
                    state,
                    weather=weather,
                    speed_level=speed_level,
                )
                interpretation = interpret_plan(plan)
                reply = interpretation.message
                if interpretation.requires_route_confirmation:
                    state.pending_plan = plan
                    state.pending_plan_request = request
                elif interpretation.kind == "destination_confirmation":
                    # 다음 짧은 답변을 정확한 장소명으로 받도록 문맥 슬롯을 고정한다.
                    state.last_target_slot = "exact_destination"
            except DRTBackendError as exc:
                backend_error = str(exc)
                # DRTBackendClient._post()가 던지는 네트워크/서버 오류는 URL·예외 이름이
                # 섞여 있어 그대로 말하면 안 된다(기술적 문구). 그 밖의 DRTBackendError
                # (예: 위치정보 동의 필요, 좌표 없음)는 이미 어르신께 말할 수 있는
                # 한국어 문장이므로 그대로 전달한다 — 안 그러면 "경로 서버 연결이
                # 원활하지 않다"는 원인 불명 메시지만 들리게 된다.
                if backend_error.startswith("DRT 백엔드 호출 실패"):
                    reply = f"{reply} 다만 경로 서버 연결이 원활하지 않아 이동 경로는 아직 확인하지 못했습니다."
                else:
                    reply = backend_error

        return TurnResult(
            assistant_reply=reply,
            analysis=analysis,
            plan=plan,
            backend_error=backend_error,
            end_call=joint.end_call,
        )
