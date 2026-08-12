"""carecall_drt(케어콜 분석+대화+DRT 계획/예약 호출)와 이 워크스페이스의 안전장치를 잇는다.

carecall_drt는 다솜이 대화·DRT 의도 분석·다중 턴 상태 관리·drt_service
`/api/plan`·`/api/reservations` 호출까지 하나의 오케스트레이터로 처리하는 "두뇌"다.
하지만 다음 네 가지는 갖고 있지 않다(모두 이 워크스페이스의 `bridge/`가 이미 갖고
있던 것이라 그대로 재사용한다):

1. 전화 통화라 GPS가 없다는 문제의 우회 — 어르신 프로필 자택 좌표 + 위치정보 동의
   확인(`bridge/location.py`). `_resolve_location()`을 `CareCallBridge.handle_utterance()`
   가 **매 턴, `process_turn`을 부르기 전에** 호출해 채운다 — carecall_drt의
   `ready_for_plan`은 `analyze_turn` 내부에서 `state.location is not None`을 직접
   검사하므로, backend 호출 시점에 지연 바인딩하면 이미 늦다(분석기가 위치 없음을
   보고 "아직 안 끝났다"고 판단해 버려 실제로는 backend가 절대 불리지 않는다).
2. 음성 규칙(TTS에 "DRT"·한자·이모지 금지) — `bridge/speech.py::sanitize()`.
   carecall_drt가 만드는 문장에는 "DRT"가 그대로 들어 있어(`carecall_drt/backend.py`
   의 `interpret_plan`) 반드시 이 필터를 통과시켜야 한다.
3. 예약 확정 뒤 문자(기록) — `bridge/notify.py`. 보호자 문자는 carecall_drt
   스키마에 동의 슬롯이 없어(사용자 결정 2026-08-11) 항상 보내지 않는다.
4. 조회 링크가 실수로 drt_service 자신을 가리키는지 검증 — `bridge/preflight.py`.

무엇을 대체했고 무엇을 남겼는지는 `docs/04_carecall_drt_이식.md`에 정리했다.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from carecall_drt import config as cc_config  # noqa: E402
from carecall_drt.analyzer import DRTAnalyzer  # noqa: E402
from carecall_drt.backend import DRTBackendClient  # noqa: E402
from carecall_drt.orchestrator import CareCallDRTOrchestrator  # noqa: E402
from carecall_drt.responses import GREETING, RuleCareResponder  # noqa: E402
from carecall_drt.schemas import Location, SessionState, TurnResult  # noqa: E402

from bridge import notify, preflight, speech  # noqa: E402
from bridge.config import settings as bridge_settings  # noqa: E402
from bridge.location import LocationUnavailable, ProfileStore, resolve_origin  # noqa: E402

CARE_CALL_DIR = PROJECT_DIR / "care_call_bot"
FAREWELL = "오늘 이야기 나눠서 즐거웠어요. 또 전화드릴게요. 건강히 지내세요."


def _load_gemini_env() -> None:
    """carecall_drt.config.Settings가 읽을 GEMINI_KEY를 care_call_bot/.env에서 불러온다.

    분석기가 원래 이 파일에서 읽었으므로(main_server/talk.py가 하던 방식과 동일)
    키 보관 위치를 옮기지 않는다. python-dotenv가 없으면 조용히 건너뛴다(규칙 폴백).
    """
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv(CARE_CALL_DIR / ".env")


def _resolve_location(profiles: ProfileStore, user_id: str, accuracy_m: float) -> tuple[Location | None, str]:
    """어르신 프로필의 자택 좌표(+위치정보 동의)로 위치를 만든다.

    동의가 없거나 프로필/좌표가 없으면 `(None, 어르신께 말할 문구)`를 돌려준다.
    drt_service는 120초보다 오래된 위치를 거절하므로 `captured_at`은 호출 시각으로
    매번 새로 찍는다(등록 좌표 자체는 변하지 않지만 "지금 이 좌표를 쓰겠다"는
    의미다 — bridge/location.py의 기존 설계와 동일).
    """
    origin = resolve_origin(profiles.get(user_id), accuracy_m=accuracy_m)
    if isinstance(origin, LocationUnavailable):
        return None, origin.spoken or "지금은 어르신 댁 위치를 확인할 수 없어요."
    location = Location(
        latitude=origin.latitude,
        longitude=origin.longitude,
        accuracy=origin.accuracy_m,
        captured_at=datetime.now(timezone.utc).isoformat(),
    )
    return location, ""


@dataclass
class CallSession:
    session_id: str
    user_id: str
    state: SessionState
    orchestrator: CareCallDRTOrchestrator
    turn_count: int = 0


@dataclass
class UtteranceOutcome:
    reply: str
    speaker: str = "dasom"          # dasom | drt | system
    call_ended: bool = False
    drt_action: str = ""
    tracking_url: str = ""
    sms_sent: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


class CareCallBridge:
    """세션마다 SessionState+오케스트레이터를 들고, 응답을 음성 규칙에 맞춰 다듬고,
    예약이 확정되면 문자를 보낸다(기록만, 실제 발송 게이트웨이는 미구현)."""

    def __init__(self) -> None:
        _load_gemini_env()
        self.settings = cc_config.Settings()
        self.settings.validate()
        self.profiles = ProfileStore.load(bridge_settings.profiles_path)
        self.analyzer = DRTAnalyzer(self.settings)
        self.responder = self._build_responder()
        self.responder_source = type(self.responder).__name__
        self._backend = DRTBackendClient(self.settings) if self.settings.drt_enabled else None
        self.sms_sender = self._build_sms_sender()
        self.sms_sender_source = type(self.sms_sender).__name__
        self._sessions: dict[str, CallSession] = {}

    def _build_responder(self):
        if self.settings.gemini_api_key:
            try:
                from carecall_drt.gemini_client import GeminiJointResponder

                return GeminiJointResponder(self.settings)
            except Exception:  # SDK 미설치·키 형식 오류 등 — 규칙 기반으로 계속 진행
                pass
        return RuleCareResponder()

    def _build_sms_sender(self):
        if (
            bridge_settings.clawops_api_key
            and bridge_settings.clawops_account_id
            and bridge_settings.clawops_from_number
        ):
            try:
                return notify.ClawOpsSmsSender(
                    bridge_settings.clawops_api_key,
                    bridge_settings.clawops_account_id,
                    bridge_settings.clawops_from_number,
                    log_path=bridge_settings.sms_log_path,
                )
            except Exception:  # clawops 패키지 미설치·키 형식 오류 등 — 기록만으로 계속 진행
                pass
        return notify.RecordingSmsSender(bridge_settings.sms_log_path)

    # ── 통화 시작/종료 ──────────────────────────────────────────────────

    def start_call(self, session_id: str, user_id: str) -> str:
        orchestrator = CareCallDRTOrchestrator(
            analyzer=self.analyzer, responder=self.responder, backend=self._backend,
        )
        self._sessions[session_id] = CallSession(
            session_id=session_id,
            user_id=user_id,
            state=SessionState(session_id=session_id),
            orchestrator=orchestrator,
        )
        return GREETING

    def end_call(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def active_count(self) -> int:
        return len(self._sessions)

    def get_state(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        return None if session is None else self._snapshot(session, ())

    # ── 발화 처리 ────────────────────────────────────────────────────────

    def handle_utterance(self, session_id: str, text: str) -> UtteranceOutcome:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)

        session.turn_count += 1

        # 분석기가 ready_for_plan을 판단할 때 state.location을 직접 들여다보므로,
        # process_turn을 부르기 전에 미리 채워야 한다(늦게 채우면 backend가 절대
        # 불리지 않는다 — 모듈 docstring 참고).
        location_reason = ""
        if self._backend is not None:
            location, location_reason = _resolve_location(
                self.profiles, session.user_id, bridge_settings.profile_accuracy_m,
            )
            session.state.location = location

        result: TurnResult = session.orchestrator.process_turn(text, session.state, history=[])

        if location_reason and self._location_was_the_only_blocker(result):
            # 목적지·동의·날짜·시간·픽업위치까지 다 모였는데 위치만 없어서 멈춘
            # 경우다. 그대로 두면 "예약 정보를 모두 확인했습니다" 같은 원인 불명의
            # 채움 문구만 반복된다 — 실제 이유(위치정보 동의)를 말씀드린다.
            reply = location_reason
        else:
            reply = speech.sanitize(result.assistant_reply) or FAREWELL
        violations = speech.tts_violations(reply)

        tracking_url = ""
        sms_sent: list[str] = []
        reservation = result.plan.get("reservation") if isinstance(result.plan, dict) else None
        if isinstance(reservation, dict):
            tracking_url, sms_sent = self._notify(session, reservation, result.plan.get("plan") or {})

        speaker = "system" if result.analysis.emergency_risk else ("drt" if result.plan is not None else "dasom")
        outcome = UtteranceOutcome(
            reply=reply,
            speaker=speaker,
            call_ended=result.end_call,
            drt_action=self._drt_action(session, result),
            tracking_url=tracking_url,
            sms_sent=sms_sent,
            state=self._snapshot(session, violations),
        )
        self._log(session, result, outcome)
        return outcome

    @staticmethod
    def _location_was_the_only_blocker(result: TurnResult) -> bool:
        """목적지·동의·날짜·시간·픽업위치가 다 모였는데도 위치가 없어 멈췄는지.

        `carecall_drt.analyzer.route_metadata`의
        ``ready_for_plan = destination_ready and consent_ready and state.location is not None``
        을 뒤집어 확인한다 — missing_slots가 비었고 예약 동의도 확정됐다면 남은
        조건은 위치뿐이다.
        """
        analysis = result.analysis
        return (
            not analysis.ready_for_plan
            and not analysis.missing_slots
            and analysis.reservation_consent == "confirmed"
            and not analysis.emergency_risk
        )

    @staticmethod
    def _drt_action(session: CallSession, result: TurnResult) -> str:
        if result.backend_error:
            return "backend_error"
        if isinstance(result.plan, dict) and isinstance(result.plan.get("reservation"), dict):
            return "reserved"
        if session.state.pending_plan is not None:
            return "awaiting_confirmation"
        if result.analysis.emergency_risk:
            return "emergency"
        return result.analysis.dialogue_stage

    def _notify(
        self, session: CallSession, reservation: dict[str, Any], plan: dict[str, Any],
    ) -> tuple[str, list[str]]:
        tracking_url = str(reservation.get("tracking_url") or "")

        # 조회 링크가 drt_service 자신을 가리키면 명백한 설정 오류다 — 어르신이
        # 문자를 눌러도 아무것도 나오지 않으므로 발송 자체를 멈춘다.
        if preflight.tracking_url_warning(tracking_url, bridge_settings.drt_base_url):
            return "", []

        profile = self.profiles.get(session.user_id)
        messages = notify.build_messages(
            reservation,
            plan,
            elder_name=(profile.name if profile else ""),
            elder_contact=(profile.contact if profile else ""),
            # 사용자 결정(2026-08-11): carecall_drt 스키마에 보호자 알림 동의 슬롯이
            # 없으므로, 다시 추가되기 전까지 보호자 문자는 항상 보내지 않는다.
            guardian_contact="",
            guardian_notify_consent="not_asked",
        )
        sent = [message for message in messages if self.sms_sender.send(message)]
        return tracking_url, [message.role for message in sent]

    def _snapshot(self, session: CallSession, violations: Any) -> dict[str, Any]:
        state = session.state
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "turn_count": session.turn_count,
            "dialogue_stage": (state.last_analysis.dialogue_stage if state.last_analysis else "unknown"),
            "destination_category": state.destination_category,
            "reservation_consent": state.reservation_consent,
            "reserved": state.pending_reservation is not None,
            "tts_violations": list(violations),
        }

    # ── 감사 로그 ──────────────────────────────────────────────────────

    def _log(self, session: CallSession, result: TurnResult, outcome: UtteranceOutcome) -> None:
        """어떤 발화가 어떤 DRT 상태로 이어졌는지 남긴다(브릿지가 하던 방식과 동일).

        개인정보(좌표·목적지)가 들어갈 수 있으므로 저장소에 커밋하지 않는다(.gitignore).
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session.session_id,
            "user_id": session.user_id,
            "drt_action": outcome.drt_action,
            "dialogue_stage": result.analysis.dialogue_stage,
            "spoken": outcome.reply,
            "backend_error": result.backend_error,
            "tracking_issued": bool(outcome.tracking_url),
            "sms_sent": outcome.sms_sent,
            "tts_violations": outcome.state.get("tts_violations", []),
        }
        try:
            path = Path(bridge_settings.audit_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass
