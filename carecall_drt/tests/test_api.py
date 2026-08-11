from __future__ import annotations

from fastapi.testclient import TestClient

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.api import SessionStore, create_app
from carecall_drt.config import Settings
from carecall_drt.orchestrator import CareCallDRTOrchestrator
from carecall_drt.responses import RuleCareResponder


def _client() -> TestClient:
    settings = Settings(gemini_policy="off")
    orchestrator = CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(settings),
        responder=RuleCareResponder(),
    )
    return TestClient(create_app(orchestrator, settings=settings, store=SessionStore()))


def test_chat_api_keeps_session_state() -> None:
    client = _client()
    first = client.post(
        "/api/chat/a/turn",
        json={
            "text": "가까운 정형외과에 가고 싶어",
            "location": {"latitude": 37.4849, "longitude": 126.9710, "accuracy": 12},
        },
    )
    assert first.status_code == 200
    assert first.json()["analysis"]["target_slot"] == "reservation_consent"
    second = client.post("/api/chat/a/turn", json={"text": "네"})
    assert second.status_code == 200
    assert second.json()["analysis"]["reservation_consent"] == "confirmed"
    assert second.json()["analysis"]["target_slot"] == "date"


def test_session_delete() -> None:
    client = _client()
    client.post("/api/chat/x/turn", json={"text": "약국에 가고 싶어"})
    response = client.delete("/api/chat/x")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
