from __future__ import annotations

import json

import httpx
import pytest

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.backend import DRTBackendClient, DRTBackendError, interpret_plan, interpret_reservation
from carecall_drt.config import Settings
from carecall_drt.schemas import Location, SessionState


def _ready_analysis():
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState(location=Location(37.4849, 126.9710, 12.5, "2026-08-11T00:00:00Z"))
    analyzer.analyze_turn(
        "오늘 오후 3시에 가까운 약국으로 집 앞에서 이동 차량 예약해줘",
        state,
        allow_internal_gemini=False,
    )
    return state.last_analysis, state


def test_plan_payload_matches_drt_algo_contract() -> None:
    analysis, state = _ready_analysis()
    assert analysis is not None
    client = DRTBackendClient(Settings(drt_base_url="http://test"), client=httpx.Client(base_url="http://test"))
    payload = client.build_plan_request(analysis, state, weather="rain", speed_level="medium")
    assert payload == {
        "latitude": 37.4849,
        "longitude": 126.971,
        "accuracy": 12.5,
        "captured_at": "2026-08-11T00:00:00Z",
        "max_walk_m": 500.0,
        "query": "약국",
        "is_specific": False,
        "expected_wait_s": 300.0,
        "weather": "rain",
        "speed_level": "medium",
    }


def test_plan_and_reservation_http_calls() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        requests.append((request.url.path, body, request.headers.get("x-relay-token")))
        if request.url.path == "/api/plan":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "plan": {
                        "status": "ready_for_confirmation",
                        "destination": {"name": "중앙약국"},
                        "boarding_station": {"name": "남성역"},
                        "alighting_station": {"name": "동작고등학교"},
                        "estimated_total_minutes": 11,
                    },
                },
            )
        return httpx.Response(
            201,
            json={
                "ok": True,
                "reservation": {
                    "call_id": "CALL-1",
                    "vehicle_id": "VEHICLE-1",
                    "estimated_arrival_s": 120,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    settings = Settings(drt_base_url="http://test", drt_relay_token="token")
    http_client = httpx.Client(base_url="http://test", transport=transport)
    client = DRTBackendClient(settings, client=http_client)
    analysis, state = _ready_analysis()
    plan, payload = client.plan(analysis, state)
    reservation = client.create_reservation(payload)
    assert interpret_plan(plan).requires_route_confirmation is True
    assert "예약" in interpret_plan(plan).message
    # call_id/vehicle_id는 전화로 들으신 어르신이 받아 적을 수 없어 말로 읽지 않는다.
    assert "CALL-1" not in interpret_reservation(reservation)
    assert "2분" in interpret_reservation(reservation)
    assert requests[0][0] == "/api/plan"
    assert requests[1][0] == "/api/reservations"
    assert all(item[2] == "token" for item in requests)


def test_reservation_rejection_is_not_treated_as_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "ok": False,
            "reservation": None,
            "reason": "현재 이용 가능한 차량이 없습니다.",
        })

    settings = Settings(drt_base_url="http://test")
    client = DRTBackendClient(
        settings,
        client=httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(DRTBackendError, match="이용 가능한 차량"):
        client.create_reservation({"query": "병원"})


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        ("walk_recommended", "walk"),
        ("needs_destination_confirmation", "destination_confirmation"),
        ("outside_service_area", "unavailable"),
        ("route_api_failed", "retry"),
    ],
)
def test_plan_status_interpretation(status: str, kind: str) -> None:
    payload = {"plan": {"status": status, "candidates": [{"name": "가나다약국"}]}}
    assert interpret_plan(payload).kind == kind


def test_missing_location_fails_before_network() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    state = SessionState()
    result = analyzer.analyze_turn("가까운 약국으로 차 불러줘", state, allow_internal_gemini=False)
    client = DRTBackendClient(Settings(drt_base_url="http://test"), client=httpx.Client(base_url="http://test"))
    with pytest.raises(DRTBackendError):
        client.build_plan_request(result, state)
