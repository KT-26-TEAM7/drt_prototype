"""메인 서버 — 통화를 소유하고 전체 흐름을 지휘한다.

프레임워크에서 "메인 서버"라고 부르던 자리다. 지금까지는 이 자리가 비어 있어서
케어콜은 CLI(`while True: input()`)였고, 두 FastAPI 서버는 대화를 몰랐다.

    사용자 발화(STT 결과)
        │
        ▼  POST /call/utterance
    ┌─────────────────────────────────────────────┐
    │ 메인 서버                                    │
    │  ① 이동 의도·목적지 분석   analyzer.py        │  ← 최신 한 마디만
    │  ② 대화 상태 관리          conversation.py    │  ← 상태 기계
    │  ③ 누가 말할지 결정        아래 _decide       │
    │  ④ 장소·정류장·경로·예약   bridge/            │
    └─────────────────────────────────────────────┘
        │                    │
        ▼                    ▼
    응답 문장(TTS로)      drt_service → 가상 DRT 서버 → 문자

핵심 두 가지:

- **대화 상태를 누적 텍스트가 아니라 상태로 관리한다.** 분석기에는 최신 발화 한
  마디만 넘기므로, 앞선 "집에 있을래"가 나중 "역시 병원 가야겠어"를 이기지 않는다.
- **한 턴에 한 마디만 말한다.** DRT가 할 말이 있으면 그것만, 없으면 다솜이가
  안부 대화를 잇는다.
"""
from __future__ import annotations

import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from bridge.config import settings as bridge_settings  # noqa: E402
from bridge.drt_client import DrtServiceClient  # noqa: E402
from bridge.location import ProfileStore  # noqa: E402
from bridge.orchestrator import (  # noqa: E402
    ACTION_ESCALATE,
    ACTION_RESERVED,
    DrtHandoff,
)
from main_server import analyzer as analyzer_module  # noqa: E402
from main_server import talk  # noqa: E402
from main_server.conversation import ConversationStore, TurnFacts  # noqa: E402


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
        app.state.sessions = ConversationStore()
        app.state.talker = talk.CareCallTalker()
        app.state.handoff = DrtHandoff(
            DrtServiceClient(),
            ProfileStore.load(bridge_settings.profiles_path),
            bridge_settings,
        )
        # 분석기는 없어도 서버가 뜬다. 얕은 규칙으로 대신한다.
        try:
            app.state.analyze = analyzer_module.load_analyzer()
            app.state.analyzer_source = "care_call_bot"
        except analyzer_module.AnalyzerUnavailable as exc:
            app.state.analyze = analyzer_module.fallback_analyze
            app.state.analyzer_source = f"fallback ({exc})"
        yield

    application = FastAPI(
        title="케어콜 DRT 메인 서버",
        version="1.0.0",
        description="통화를 소유하고 대화 상태·의도 분석·DRT 예약을 지휘합니다.",
        lifespan=lifespan,
    )

    @application.get("/", tags=["system"])
    def root() -> dict:
        return {
            "status": "ok",
            "service": "케어콜 DRT 메인 서버",
            "analyzer": application.state.analyzer_source,
            "conversation": "llm" if application.state.talker.uses_llm else "fallback",
            "drt_service": bridge_settings.drt_base_url,
            "active_calls": application.state.sessions.active_count(),
            "docs": "/docs",
        }

    @application.post("/call/start", response_model=StartCallResponse, tags=["call"],
                      dependencies=[Depends(require_call_token)])
    def start_call(payload: StartCallRequest) -> StartCallResponse:
        session_id = f"CALL-{uuid.uuid4().hex[:10].upper()}"
        application.state.sessions.create(session_id, payload.user_id)
        # 브릿지 세션은 사용자별로 남아 있다. 지난 통화에서 되물어 둔 것이 그대로면
        # 이번 통화의 첫 마디를 그 답으로 잘못 받아들인다. 새 통화는 새로 시작한다.
        application.state.handoff.sessions.reset(payload.user_id)
        # 첫인사는 고정 멘트다. 도입부가 매번 같아야 어르신이 혼란스럽지 않다.
        return StartCallResponse(session_id=session_id, reply=talk.GREETING)

    @application.post("/call/utterance", response_model=UtteranceResponse, tags=["call"],
                      dependencies=[Depends(require_call_token)])
    def handle_utterance(payload: UtteranceRequest) -> UtteranceResponse:
        state = application.state.sessions.get(payload.session_id)
        if state is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "통화 세션을 찾을 수 없습니다.")

        handoff: DrtHandoff = application.state.handoff

        # 되물어 둔 것이 있으면 이번 발화를 그 답으로 먼저 해석한다.
        # (후보 선택, 예약 확인 — 브릿지가 상태를 들고 있다)
        session = handoff.sessions.get(state.user_id)
        if session.awaiting:
            outcome = handoff.handle_reply(state.user_id, payload.text)
            if outcome.action == ACTION_RESERVED:
                state.mark_reserved()
            if outcome.text:
                return _drt_response(outcome, state)

        # ① 최신 발화 한 마디만 분석한다. 대화 전체를 넘기지 않는 것이 핵심이다.
        turn = application.state.analyze(payload.text)
        # ② 상태 기계에 병합한다. 나중 발화가 앞선 발화를 뒤집을 수 있다.
        state.apply(TurnFacts.from_analyzer_output(turn))
        # ③ 누적된 상태를 분석기 형태로 되돌려 브릿지에 넘긴다.
        outcome = handoff.handle_analysis(state.user_id, state.to_analyzer_output())
        if outcome.action == ACTION_RESERVED:
            state.mark_reserved()

        # ④ 한 턴에 한 마디만. DRT가 할 말이 있으면 그것만 말한다.
        if outcome.text:
            return _drt_response(outcome, state)

        # DRT 쪽에서 할 말이 없으면 다솜이가 안부 대화를 잇는다.
        reply, ended = application.state.talker.reply(payload.session_id, payload.text)
        return UtteranceResponse(
            reply=reply or talk.FAREWELL,
            speaker="dasom",
            call_ended=ended,
            drt_action=outcome.code,
            state=state.snapshot(),
        )

    @application.post("/call/end", tags=["call"], dependencies=[Depends(require_call_token)])
    def end_call(payload: UtteranceRequest | None = None, session_id: str = "") -> dict:
        target = session_id or (payload.session_id if payload else "")
        if not target:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "session_id가 필요합니다.")
        state = application.state.sessions.get(target)
        if state is not None:
            # 통화가 끝나면 브릿지 쪽 되물음 상태도 함께 정리한다.
            application.state.handoff.sessions.reset(state.user_id)
        application.state.talker.end(target)
        ended = application.state.sessions.end(target)
        return {"ok": ended, "reply": talk.FAREWELL}

    @application.get("/call/{session_id}/state", tags=["call"],
                     dependencies=[Depends(require_call_token)])
    def call_state(session_id: str) -> dict:
        state = application.state.sessions.get(session_id)
        if state is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "통화 세션을 찾을 수 없습니다.")
        return state.snapshot()

    return application


def _drt_response(outcome: Any, state: Any) -> UtteranceResponse:
    return UtteranceResponse(
        reply=outcome.text,
        speaker="system" if outcome.action == ACTION_ESCALATE else "drt",
        expects=outcome.expects,
        drt_action=outcome.code,
        tracking_url=outcome.tracking_url,
        sms_sent=[message.role for message in outcome.sms_messages],
        state=state.snapshot(),
    )


app = create_app()
