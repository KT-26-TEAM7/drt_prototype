"""다솜이-DRT 통합 FastAPI.

팀의 전화/STT 계층이 텍스트를 전달할 때 사용할 수 있는 얇은 세션 API다.
프로토타입은 메모리 세션 저장소를 사용하며, 운영 환경에서는 Redis/DB로 교체해야 한다.
"""

from __future__ import annotations

import os
import threading

from dotenv import load_dotenv

load_dotenv()
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .analyzer import DRTAnalyzer
from .backend import DRTBackendClient
from .config import Settings
from .gemini_client import GeminiJointResponder, GeminiUnavailableError
from .orchestrator import CareCallDRTOrchestrator
from .responses import RuleCareResponder
from .schemas import Location, SessionState


class LocationInput(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    captured_at: str | None = None


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    location: LocationInput | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    weather: str | None = None
    speed_level: str | None = None


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        with self._lock:
            return self._states.setdefault(session_id, SessionState(session_id=session_id))

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._states.pop(session_id, None) is not None


def build_default_orchestrator(settings: Settings) -> CareCallDRTOrchestrator:
    mode = os.getenv("CARE_MODEL", "rule").strip().lower()
    if mode == "gemini":
        try:
            responder = GeminiJointResponder(settings)
        except GeminiUnavailableError as exc:
            raise RuntimeError(str(exc)) from exc
    elif mode == "rule":
        responder = RuleCareResponder()
    else:
        raise ValueError("CARE_MODEL은 rule 또는 gemini여야 합니다. Mi:dm은 chat_demo.py에서 실행하세요.")

    backend = DRTBackendClient(settings) if settings.drt_enabled else None
    return CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(settings),
        responder=responder,
        backend=backend,
    )


def create_app(
    orchestrator: CareCallDRTOrchestrator | None = None,
    *,
    settings: Settings | None = None,
    store: SessionStore | None = None,
) -> FastAPI:
    settings = settings or Settings()
    store = store or SessionStore()
    orchestrator = orchestrator or build_default_orchestrator(settings)

    app = FastAPI(title="다솜이 케어콜 + DRT 통합 API", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "care_model": os.getenv("CARE_MODEL", "rule"),
            "gemini_policy": settings.gemini_policy,
            "drt_backend_enabled": bool(orchestrator.backend),
        }

    @app.post("/api/chat/{session_id}/turn")
    def turn(session_id: str, request: TurnRequest) -> dict[str, Any]:
        state = store.get(session_id)
        if request.location is not None:
            state.location = Location(**request.location.model_dump())
        try:
            result = orchestrator.process_turn(
                request.text,
                state,
                request.history,
                weather=request.weather,
                speed_level=request.speed_level,
            )
            return result.to_dict()
        except Exception as exc:  # API 경계에서 원인을 보존해 500으로 보고
            raise HTTPException(status_code=500, detail=f"통합 처리 실패: {type(exc).__name__}: {exc}") from exc

    @app.delete("/api/chat/{session_id}")
    def reset_session(session_id: str) -> dict[str, Any]:
        return {"ok": True, "deleted": store.delete(session_id)}

    return app


app = create_app()
