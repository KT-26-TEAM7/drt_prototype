from __future__ import annotations

import json

import httpx

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.backend import DRTBackendClient
from carecall_drt.config import Settings
from carecall_drt.orchestrator import CareCallDRTOrchestrator
from carecall_drt.schemas import JointLLMResult, Location, SessionState


class FakeJointResponder:
    def __init__(self, semantic: dict | None = None):
        self.semantic = semantic
        self.calls = 0

    def respond(self, history, user_text, *, drt_candidate, analysis_hint, state):
        self.calls += 1
        return JointLLMResult(
            assistant_reply="말씀해 주셔서 고맙습니다. 언제 가실까요?",
            semantic=self.semantic,
            semantic_call_attempted=True,
        )


class CountingEnricher:
    def __init__(self):
        self.calls = 0

    def analyze(self, text):
        self.calls += 1
        return {}, 1.0


def test_joint_gemini_mode_never_makes_second_semantic_call() -> None:
    enricher = CountingEnricher()
    settings = Settings(gemini_policy="candidate")
    analyzer = DRTAnalyzer(settings, semantic_enricher=enricher)
    responder = FakeJointResponder(
        {
            "visit_intent": True,
            "destination_category": "medical_orthopedics",
            "destination_candidates": ["정형외과"],
            "specific_place": "",
            "place_preference": "nearby",
            "extracted_keywords": ["무릎"],
        }
    )
    orchestrator = CareCallDRTOrchestrator(analyzer=analyzer, responder=responder)
    result = orchestrator.process_turn("무릎이 아파서 병원에 가고 싶어", SessionState())
    assert responder.calls == 1
    assert enricher.calls == 0
    assert result.analysis.gemini_used is True
    assert result.assistant_reply.count("?") == 1


def test_casual_turn_does_not_add_drt_question() -> None:
    responder = FakeJointResponder(None)
    orchestrator = CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(Settings(gemini_policy="off")),
        responder=responder,
    )
    result = orchestrator.process_turn("오늘 밥은 먹었어", SessionState())
    assert "어디 다녀오실" not in result.assistant_reply


def test_end_to_end_plan_then_confirm_reservation() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/plan":
            return httpx.Response(
                200,
                json={
                    "plan": {
                        "status": "ready_for_confirmation",
                        "destination": {"name": "중앙약국"},
                        "boarding_station": {"name": "남성역"},
                        "alighting_station": {"name": "동작고등학교"},
                        "estimated_total_minutes": 9,
                    }
                },
            )
        return httpx.Response(
            201,
            json={
                "ok": True,
                "reservation": {
                    "call_id": "CALL-ABC",
                    "vehicle_id": "VEHICLE-001",
                    "estimated_arrival_s": 180,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    settings = Settings(gemini_policy="off", drt_base_url="http://test")
    backend = DRTBackendClient(settings, client=httpx.Client(base_url="http://test", transport=transport))
    orchestrator = CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(settings),
        responder=FakeJointResponder(None),
        backend=backend,
    )
    state = SessionState(location=Location(37.4849, 126.9710, 10))

    first = orchestrator.process_turn(
        "오늘 오후 3시에 가까운 약국으로 집 앞에서 이동 차량 예약해줘",
        state,
    )
    assert calls == ["/api/plan"]
    assert state.pending_plan is not None
    assert "이 경로로 예약할까요" in first.assistant_reply

    second = orchestrator.process_turn("네", state)
    assert calls == ["/api/plan", "/api/reservations"]
    # call_id/vehicle_id는 전화로 들으신 어르신이 받아 적을 수 없어 말로 읽지 않는다.
    assert "CALL-ABC" not in second.assistant_reply
    assert "3분" in second.assistant_reply
    assert state.pending_plan is None

    # 실제 통화(2026-08-12)에서 재현된 이중 배차 버그: 예약이 끝난 뒤에도 목적지·
    # 날짜·시간·픽업 슬롯이 SessionState에 그대로 남아 있어 ready_for_reservation이
    # 계속 True였다. 그래서 "고마워" 같은 인사말에도 매번 같은 경로를 다시 계획해
    # 버렸고, 답이 우연히 긍정으로 들리면 차량이 한 번 더 배차됐다. 예약 완료 후
    # 어떤 발화가 와도 더 이상 /api/plan을 다시 부르면 안 된다.
    third = orchestrator.process_turn("끝난 걸까 고마워", state)
    assert calls == ["/api/plan", "/api/reservations"]  # 늘어나면 안 된다
    assert third.plan is None
    assert state.pending_plan is None


def test_pending_route_negative_does_not_reserve() -> None:
    settings = Settings(gemini_policy="off")
    orchestrator = CareCallDRTOrchestrator(
        analyzer=DRTAnalyzer(settings),
        responder=FakeJointResponder(None),
    )
    state = SessionState()
    state.pending_plan = {"plan": {"status": "ready_for_confirmation"}}
    state.pending_plan_request = {"query": "약국"}
    state.last_analysis = DRTAnalyzer(settings).analyze_turn("약국 가고 싶어", SessionState(), allow_internal_gemini=False)
    result = orchestrator.process_turn("아니요", state)
    assert "예약하지 않을게요" in result.assistant_reply
    assert state.pending_plan is None
