"""메인 서버 — 통화를 소유하고 전체 흐름을 지휘한다.

    사용자 발화(STT 결과)
        │
        ▼  POST /call/utterance
    ┌─────────────────────────────────────────────────────┐
    │ 메인 서버                                            │
    │  carecall_drt.CareCallDRTOrchestrator                │
    │   ① 대화 분석 + 다중 턴 상태     analyzer.py/schemas  │
    │   ② 다솜이 응답(+DRT 의미 보강)  responder            │
    │   ③ DRT 계획/예약 호출           backend.py           │
    │  main_server.care_bridge.CareCallBridge (이 워크스페이스 어댑터)  │
    │   ④ 위치(GPS 없음 우회)·음성규칙(TTS)·문자·추적링크검증 │
    └─────────────────────────────────────────────────────┘
        │                    │
        ▼                    ▼
    응답 문장(TTS로)      drt_service → 가상 DRT 서버 → 문자

carecall_drt 자체가 "최신 발화만 보고도 앞선 거절을 뒤집을 수 있는" 다중 턴
`SessionState`를 갖고 있어(이전에는 `main_server/conversation.py`가 이 문제를
따로 우회했다), 여기서는 세션마다 그 상태를 들고 있기만 하면 된다. 무엇을
대체했는지는 `docs/04_carecall_drt_이식.md` 참고.
"""
from __future__ import annotations

import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bridge.config import settings as bridge_settings  # noqa: E402
from main_server.care_bridge import FAREWELL, CareCallBridge  # noqa: E402
from main_server.clawops_webhook import extract_call_id_and_phone, parse_payload  # noqa: E402


# ── 인증 ─────────────────────────────────────────────────────────────────
#
# 로컬 개발에서는 아무도 이 값을 설정한 적이 없으므로 그대로 인증 없이 열려 있다.
# 클라우드에 배포해 인터넷에 공개될 때만 MAIN_SERVER_TOKEN을 넣어 잠근다
# (drt_service의 RELAY_API_TOKEN과 같은 패턴이지만, 신뢰 경계가 다르므로 별도 값).

_MAIN_SERVER_TOKEN = os.getenv("MAIN_SERVER_TOKEN", "").strip()
_call_token_header = APIKeyHeader(name="X-Call-Token", auto_error=False)


async def require_call_token(x_call_token: str | None = Security(_call_token_header)) -> None:
    if _MAIN_SERVER_TOKEN and x_call_token != _MAIN_SERVER_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 호출 토큰입니다.")


# ── 요청/응답 ────────────────────────────────────────────────────────────


class StartCallRequest(BaseModel):
    user_id: str = Field(min_length=1, examples=["elder_demo_01"])
    # ClawOps가 이 통화에 부여한 통화 ID(있으면). AI 에이전트가 시스템 컨텍스트에서
    # 그대로 전달하는 값이라 음성 전사 대상이 아니다 — 실제 전화번호는 별도로
    # /webhooks/clawops/call-status 웹훅이 이 ID와 짝지어 미리 전달한다
    # (main_server/clawops_webhook.py 참고).
    clawops_call_id: str = ""


class StartCallResponse(BaseModel):
    session_id: str
    reply: str
    expects: str = ""


class UtteranceRequest(BaseModel):
    session_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=500)


class UtteranceResponse(BaseModel):
    """`reply`를 그대로 TTS로 읽어 주면 된다."""

    reply: str
    speaker: str          # dasom | drt | system
    expects: str = ""     # 다음 턴에 기다리는 답(destination_choice 등)
    call_ended: bool = False
    drt_action: str = ""  # 이번 턴에 DRT 쪽에서 일어난 일
    tracking_url: str = ""
    sms_sent: list[str] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)


# ── 앱 ───────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.care = CareCallBridge()
        yield

    application = FastAPI(
        title="케어콜 DRT 메인 서버",
        version="1.0.0",
        description="통화를 소유하고 대화 상태·의도 분석·DRT 예약을 지휘합니다.",
        lifespan=lifespan,
    )

    @application.get("/", tags=["system"])
    def root() -> dict:
        care: CareCallBridge = application.state.care
        return {
            "status": "ok",
            "service": "케어콜 DRT 메인 서버",
            "responder": care.responder_source,
            "sms_sender": care.sms_sender_source,
            "drt_backend_enabled": care.settings.drt_enabled,
            "drt_backend_url": care.settings.drt_base_url,
            "active_calls": care.active_count(),
            "docs": "/docs",
        }

    @application.post("/webhooks/clawops/call-status", tags=["webhooks"])
    async def clawops_call_status(request: Request) -> dict:
        """ClawOps가 통화 상태 변경 시 보내는 콜백(`Calls.create`의
        `status_callback`). 실제 통화 상대 번호를 `call_id`와 함께 미리 받아
        두었다가, `/call/start`가 `clawops_call_id`로 찾아 쓴다(§clawops_webhook.py).

        **2026-08-12 시점 주의**: 정확한 필드명을 문서로 확인 못 해 여러 후보를
        시도한다. 처음 실제 웹훅이 오면 아래 로그로 실제 키를 확인해야 한다.
        """
        care: CareCallBridge = application.state.care
        raw_body = await request.body()
        content_type = request.headers.get("content-type", "")
        fields = parse_payload(content_type, raw_body)

        secret = bridge_settings.clawops_webhook_signing_secret
        if secret:
            try:
                import clawops

                clawops.webhooks.Webhooks().verify(
                    url=str(request.url),
                    params=fields,
                    signature=request.headers.get("x-signature", ""),
                    signing_key=secret,
                )
            except Exception as exc:
                print(f"[ClawOps webhook] 서명 검증 실패: {exc}", flush=True)
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "서명 검증 실패")

        call_id, phone, call_status = extract_call_id_and_phone(fields)
        # 전화번호는 개인정보라 본문 전체는 안 남기고, 실제 필드명 확인용으로
        # 키 목록만 남긴다(한동안만 — 필드명이 확정되면 이 줄은 지워도 된다).
        print(
            f"[ClawOps webhook] call_id={call_id!r} status={call_status!r} "
            f"phone_found={bool(phone)} raw_keys={list(fields.keys())}",
            flush=True,
        )
        if call_id and phone:
            care.pending_calls.store(call_id, phone)
        return {"ok": True}

    @application.post("/call/start", response_model=StartCallResponse, tags=["call"],
                      dependencies=[Depends(require_call_token)])
    def start_call(payload: StartCallRequest) -> StartCallResponse:
        session_id = f"CALL-{uuid.uuid4().hex[:10].upper()}"
        care: CareCallBridge = application.state.care
        # 첫인사는 고정 멘트다. 도입부가 매번 같아야 어르신이 혼란스럽지 않다.
        greeting = care.start_call(session_id, payload.user_id, payload.clawops_call_id)
        return StartCallResponse(session_id=session_id, reply=greeting)

    @application.post("/call/utterance", response_model=UtteranceResponse, tags=["call"],
                      dependencies=[Depends(require_call_token)])
    def handle_utterance(payload: UtteranceRequest) -> UtteranceResponse:
        care: CareCallBridge = application.state.care
        try:
            outcome = care.handle_utterance(payload.session_id, payload.text)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "통화 세션을 찾을 수 없습니다.")

        return UtteranceResponse(
            reply=outcome.reply,
            speaker=outcome.speaker,
            # 예약 확인 대기 중일 때만 "네/아니오"류 답을 기다린다고 알려 준다.
            expects="reservation_confirm" if outcome.drt_action == "awaiting_confirmation" else "",
            call_ended=outcome.call_ended,
            drt_action=outcome.drt_action,
            tracking_url=outcome.tracking_url,
            sms_sent=outcome.sms_sent,
            state=outcome.state,
        )

    @application.post("/call/end", tags=["call"], dependencies=[Depends(require_call_token)])
    def end_call(payload: UtteranceRequest | None = None, session_id: str = "") -> dict:
        target = session_id or (payload.session_id if payload else "")
        if not target:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "session_id가 필요합니다.")
        care: CareCallBridge = application.state.care
        care.end_call(target)
        return {"ok": True, "reply": FAREWELL}

    @application.get("/call/{session_id}/state", tags=["call"],
                     dependencies=[Depends(require_call_token)])
    def call_state(session_id: str) -> dict:
        care: CareCallBridge = application.state.care
        state = care.get_state(session_id)
        if state is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "통화 세션을 찾을 수 없습니다.")
        return state

    return application


app = create_app()
