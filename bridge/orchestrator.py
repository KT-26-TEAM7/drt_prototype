"""브릿지 진입점. 케어콜 분석 결과 하나를 받아 DRT 처리까지 끌고 간다.

    분석 결과 JSON
        -> 게이트(호출해도 되나)          bridge/gate.py
        -> 검색어 변환(무엇을 찾나)        bridge/mapping.py
        -> 출발 좌표 확보(어디서 타나)     bridge/location.py
        -> drt_service 호출               bridge/drt_client.py
        -> 음성 문장 생성(뭐라고 말하나)    bridge/speech.py

되물어야 하는 답(후보 선택, 예약 확인)은 `handle_reply()`로 이어서 처리한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bridge import gate, mapping, notify, preflight, speech
from bridge.config import Settings, settings as default_settings
from bridge.contract import CareCallResult
from bridge.drt_client import DrtService, DrtServiceError
from bridge.location import LocationUnavailable, Origin, ProfileStore, resolve_origin
from bridge.notify import RecordingSmsSender, SmsMessage, SmsSender
from bridge.session import Session, SessionStore, parse_choice, parse_yes_no
from bridge.speech import EXPECT_DESTINATION_CHOICE, EXPECT_RESERVATION_CONFIRM, Utterance

# 브릿지가 한 턴에 내린 결론.
ACTION_SPEAK = "speak"  # 말만 하고 끝 (되물음 포함)
ACTION_ESCALATE = "escalate_emergency"
ACTION_NOTIFY_GUARDIAN = "notify_guardian"
ACTION_RESERVED = "reserved"
ACTION_SKIP = "skip"


@dataclass(frozen=True, slots=True)
class HandoffOutcome:
    """이번 턴의 결과. 케어콜 쪽은 `spoken.text`를 읽어 주면 된다."""

    action: str
    code: str
    spoken: Utterance | None = None
    drt_request: dict[str, Any] | None = None
    drt_response: dict[str, Any] | None = None
    guardian_message: str = ""
    # 배차 서버가 붙어 있을 때만 채워진다. 음성으로는 읽지 않고 문자로 보낸다.
    tracking_url: str = ""
    sms_messages: list[SmsMessage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.spoken.text if self.spoken else ""

    @property
    def expects(self) -> str:
        return self.spoken.expects if self.spoken else ""


class DrtHandoff:
    def __init__(
        self,
        service: DrtService,
        profiles: ProfileStore | None = None,
        config: Settings | None = None,
        sessions: SessionStore | None = None,
        sms_sender: SmsSender | None = None,
    ) -> None:
        self.config = config or default_settings
        self.service = service
        self.profiles = profiles or ProfileStore.load(self.config.profiles_path)
        self.sessions = sessions or SessionStore()
        # 실제 문자 발송 게이트웨이는 아직 없다. 기본값은 기록만 하는 구현이다.
        self.sms_sender = sms_sender or RecordingSmsSender(self.config.sms_log_path)

    # ── 1턴: 분석 결과를 받는다 ────────────────────────────────────────────

    def handle_analysis(
        self,
        user_id: str,
        analyzer_output: dict[str, Any],
        *,
        device_location: Origin | None = None,
    ) -> HandoffOutcome:
        result = CareCallResult.from_analyzer_output(analyzer_output)
        session = self.sessions.get(user_id)
        # 예약이 확정되는 시점에는 분석 결과가 없으므로, 보호자 통보 동의를 여기서 기억해 둔다.
        session.guardian_notify_consent = result.guardian_notify_consent

        decision = gate.evaluate(result)
        if decision.action == gate.ACTION_ESCALATE:
            session.clear_pending()
            return self._log(user_id, HandoffOutcome(
                ACTION_ESCALATE, decision.code, speech.say(decision.spoken, kind="emergency"),
            ))
        if decision.action == gate.ACTION_SKIP:
            session.clear_pending()
            return self._log(user_id, HandoffOutcome(ACTION_SKIP, decision.code))
        if decision.action == gate.ACTION_NOTIFY_GUARDIAN:
            return self._log(user_id, self._guardian_outcome(user_id, session))
        if decision.action == gate.ACTION_ASK_USER:
            # 분석기가 이미 만들어 둔 질문을 그대로 쓴다. 브릿지가 다시 지어내면
            # 케어콜 쪽 대화 흐름과 어긋난다.
            return self._log(user_id, HandoffOutcome(
                ACTION_SPEAK, decision.code, speech.say(decision.spoken, kind="ask"),
                notes=list(decision.notes),
            ))

        query = mapping.build_query(result)
        if isinstance(query, mapping.QueryUnavailable):
            return self._log(user_id, HandoffOutcome(
                ACTION_SPEAK, query.code, speech.say(query.spoken, EXPECT_DESTINATION_CHOICE, "ask"),
                notes=list(decision.notes),
            ))

        origin = resolve_origin(
            self.profiles.get(user_id),
            accuracy_m=self.config.profile_accuracy_m,
            device_location=device_location,
        )
        if isinstance(origin, LocationUnavailable):
            return self._log(user_id, HandoffOutcome(
                ACTION_SPEAK, origin.code, speech.say(origin.spoken, kind="ask"),
                notes=list(decision.notes),
            ))

        return self._log(user_id, self._run_plan(
            session, origin, query.query, query.is_specific, notes=list(decision.notes),
        ))

    # ── 2턴 이후: 되물음에 대한 답을 받는다 ────────────────────────────────

    def handle_reply(self, user_id: str, text: str) -> HandoffOutcome:
        session = self.sessions.get(user_id)

        if session.awaiting == EXPECT_DESTINATION_CHOICE:
            return self._log(user_id, self._handle_choice(session, text))
        if session.awaiting == EXPECT_RESERVATION_CONFIRM:
            return self._log(user_id, self._handle_confirm(session, text))
        return HandoffOutcome(ACTION_SKIP, "nothing_awaited")

    def _handle_choice(self, session: Session, text: str) -> HandoffOutcome:
        if not session.candidates:
            # 고를 후보가 없는데 선택을 기다리면 "중에 어디로 모실까요?" 같은 빈 문장이 나간다.
            # 새 목적지는 분석기가 다음 턴에 뽑아 주므로 여기서는 기다림을 푼다.
            session.clear_pending()
            return HandoffOutcome(
                ACTION_SPEAK, "awaiting_new_destination",
                speech.say("어디로 가고 싶으신지 다시 말씀해 주시겠어요?", kind="ask"),
            )

        index = parse_choice(text, session.candidates)
        if index is None:
            listed = ", ".join(
                str(item.get("name") or "") for item in
                session.candidates[: self.config.max_spoken_candidates]
            )
            return HandoffOutcome(
                ACTION_SPEAK, "choice_unclear",
                speech.say(f"{listed} 중에 어디로 모실까요?", EXPECT_DESTINATION_CHOICE, "ask"),
            )

        chosen = session.candidates[index]
        name = str(chosen.get("name") or "")
        origin = self._origin_from_payload(session.pending_payload)
        if origin is None:
            return HandoffOutcome(ACTION_SPEAK, "origin_lost",
                                  speech.say("다시 한번 도와드릴게요. 어디로 가실까요?", kind="ask"))
        # drt_service의 /api/reservations는 "어느 후보를 골랐는지"를 받지 못한다.
        # 그래서 고르신 이름으로 정확명 검색을 다시 돌려 한 곳으로 좁힌다.
        return self._run_plan(session, origin, name, True, notes=["reselected_from_candidates"])

    def _handle_confirm(self, session: Session, text: str) -> HandoffOutcome:
        answer = parse_yes_no(text)
        if answer is None:
            return HandoffOutcome(
                ACTION_SPEAK, "confirm_unclear",
                speech.say("차를 불러 드릴까요? 네 또는 아니오로 말씀해 주세요.",
                           EXPECT_RESERVATION_CONFIRM, "ask"),
            )
        if answer is False:
            payload = dict(session.pending_payload)
            session.clear_pending()
            return HandoffOutcome(
                ACTION_SKIP, "reservation_declined",
                speech.say("네, 알겠습니다. 필요하시면 언제든 말씀해 주세요."),
                drt_request=payload or None,
            )

        payload = dict(session.pending_payload)
        if not payload:
            session.clear_pending()
            return HandoffOutcome(ACTION_SPEAK, "no_pending_reservation",
                                  speech.say("어디로 가실지 다시 한번 말씀해 주시겠어요?", kind="ask"))

        try:
            response = self.service.reserve(payload)
        except DrtServiceError as exc:
            return HandoffOutcome(
                ACTION_SPEAK, "reserve_failed",
                speech.say("지금은 차를 부르지 못했어요. 잠시 뒤에 다시 도와드릴게요."),
                drt_request=payload, notes=[str(exc)],
            )

        boarding = (session.last_plan.get("boarding") or {}).get("name", "")
        utterance = speech.spoken_for_reservation(response, boarding)
        plan = response.get("plan") or session.last_plan
        reservation = response.get("reservation")
        session.last_plan = plan

        sent_messages: list[SmsMessage] = []
        tracking_url = ""
        notes: list[str] = []
        if isinstance(reservation, dict):
            tracking_url = str(reservation.get("tracking_url") or "")
            # 조회 링크가 drt_service를 가리키면 배차 서버의 TRACKING_BASE_URL이 잘못된 것이다.
            # 열리지 않는 링크를 어르신께 문자로 보내면 안 되므로 발송을 멈춘다.
            warning = preflight.tracking_url_warning(tracking_url, self.config.drt_base_url)
            if warning:
                notes.append(warning)
            else:
                sent_messages = self._send_notifications(session, reservation, plan)

        session.clear_pending()
        return HandoffOutcome(
            ACTION_RESERVED if reservation else ACTION_SPEAK,
            "reserved" if reservation else "reservation_not_needed",
            utterance, drt_request=payload, drt_response=response,
            tracking_url=tracking_url, sms_messages=sent_messages, notes=notes,
        )

    def _send_notifications(
        self, session: Session, reservation: dict[str, Any], plan: dict[str, Any],
    ) -> list[SmsMessage]:
        """예약 확정 문자를 보낸다(현재는 기록만).

        보호자 문자는 통보 동의가 확인된 경우에만 나간다. 배차 서버를 쓰지 않는
        MOCK 모드에서는 보낼 링크가 없어 아무것도 만들어지지 않는다.
        """
        profile = self.profiles.get(session.user_id)
        messages = notify.build_messages(
            reservation,
            plan,
            elder_name=(profile.name if profile else ""),
            elder_contact=(profile.contact if profile else ""),
            guardian_contact=(profile.guardian_contact if profile else ""),
            guardian_notify_consent=session.guardian_notify_consent,
        )
        return [message for message in messages if self.sms_sender.send(message)]

    # ── 공통 ───────────────────────────────────────────────────────────────

    def _run_plan(
        self,
        session: Session,
        origin: Origin,
        query: str,
        is_specific: bool,
        *,
        notes: list[str],
    ) -> HandoffOutcome:
        payload = self._plan_payload(origin, query, is_specific)
        try:
            response = self.service.plan(payload)
        except DrtServiceError as exc:
            return HandoffOutcome(
                ACTION_SPEAK, "plan_failed",
                speech.say("지금 길 찾기가 잘 되지 않네요. 잠시 뒤에 다시 알아봐 드릴게요."),
                drt_request=payload, notes=notes + [str(exc)],
            )

        plan = response.get("plan") or {}
        utterance = speech.spoken_for_plan(plan, max_candidates=self.config.max_spoken_candidates)

        session.last_plan = plan
        session.awaiting = utterance.expects
        session.candidates = plan.get("candidates") or []
        # 예약 확인을 기다리는 동안에만 요청 본문을 들고 있는다. /api/reservations가
        # /api/plan과 같은 본문을 받기 때문에 그대로 재사용할 수 있다.
        session.pending_payload = payload if utterance.expects == EXPECT_RESERVATION_CONFIRM else {}
        if utterance.expects == EXPECT_DESTINATION_CHOICE:
            # 후보를 고르신 뒤 같은 출발지로 다시 검색해야 하므로 좌표는 유지한다.
            session.pending_payload = payload
        session.touch()

        return HandoffOutcome(
            ACTION_SPEAK, plan.get("status") or "unknown", utterance,
            drt_request=payload, drt_response=response, notes=notes,
        )

    def _plan_payload(self, origin: Origin, query: str, is_specific: bool) -> dict[str, Any]:
        # drt_service의 PlanRequest는 extra="forbid"라 정의되지 않은 키를 넣으면 422가 난다.
        payload = origin.to_payload()
        payload.update({
            "query": query,
            "is_specific": is_specific,
            "expected_wait_s": self.config.expected_wait_s,
        })
        return payload

    @staticmethod
    def _origin_from_payload(payload: dict[str, Any]) -> Origin | None:
        if not payload:
            return None
        try:
            return Origin(
                latitude=float(payload["latitude"]),
                longitude=float(payload["longitude"]),
                accuracy_m=float(payload.get("accuracy") or 30.0),
                source="session_replay",
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _guardian_outcome(self, user_id: str, session: Session) -> HandoffOutcome:
        profile = self.profiles.get(user_id)
        plan = session.last_plan
        if not plan:
            return HandoffOutcome(ACTION_SKIP, "no_reservation_to_report")

        total_s = plan.get("total_travel_time_s")
        message = speech.guardian_message(
            elder_name=(profile.name if profile else "어르신"),
            destination=(plan.get("destination") or {}).get("name", "목적지"),
            boarding_name=(plan.get("boarding") or {}).get("name", ""),
            total_minutes=round(total_s / 60) if isinstance(total_s, (int, float)) else None,
        )
        # 실제 발송은 브릿지 밖(알림 채널)의 몫이다. drt_service에는 보호자 알림 API가 없다.
        return HandoffOutcome(
            ACTION_NOTIFY_GUARDIAN, "guardian_message_ready",
            speech.say("네, 따님께 예약 내용을 알려 드릴게요."),
            guardian_message=message,
        )

    # ── 감사 로그 ──────────────────────────────────────────────────────────

    def _log(self, user_id: str, outcome: HandoffOutcome) -> HandoffOutcome:
        """어떤 발화가 어떤 DRT 요청으로 넘어갔는지 남긴다.

        개인정보(좌표·목적지)가 들어가므로 저장소에 커밋하지 않는다(.gitignore).
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "action": outcome.action,
            "code": outcome.code,
            "spoken": outcome.text,
            "query": (outcome.drt_request or {}).get("query"),
            "is_specific": (outcome.drt_request or {}).get("is_specific"),
            "plan_status": ((outcome.drt_response or {}).get("plan") or {}).get("status"),
            # 링크 자체는 조회 권한이라 로그에 남기지 않고, 발급 여부만 기록한다.
            "tracking_issued": bool(outcome.tracking_url),
            "sms_sent": [message.role for message in outcome.sms_messages],
            "notes": outcome.notes,
        }
        try:
            path = Path(self.config.audit_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            # 로그를 못 남긴다고 통화를 끊을 이유는 없다.
            pass
        return outcome
