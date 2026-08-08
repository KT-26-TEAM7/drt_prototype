from __future__ import annotations

import asyncio
import json

import httpx

from app.clients.drt_client import HttpDrtClient, MAX_STOP_TO_STOP_S, MIN_STOP_TO_STOP_S


def test_missing_eta_estimate_rejects_without_calling_dispatch_server():
    """ETA 모델이 소요시간을 못 냈으면(stop_to_stop_travel_s=None) 배차 서버에
    1초 같은 지어낸 값을 보내는 대신, 요청 자체를 만들지 않고 거절해야 한다."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HttpDrtClient("http://dispatch.example", client=async_client)
        result = await client.request_call(
            boarding_station_id=1,
            alighting_station_id=2,
            expected_wait_s=300,
            stop_to_stop_travel_s=None,
        )
        await async_client.aclose()
        return result

    result = asyncio.run(run())
    assert called is False
    assert result.status == "rejected"
    assert "stop_to_stop_travel_s" in (result.reason or "")


def test_real_eta_estimate_is_sent_as_is():
    """ETA 모델이 계산한 실제 값(예: 142.4초)이 반올림돼 그대로 배차 서버에 전달돼야 한다."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "call_id": "CALL-1", "vehicle_id": "VEHICLE-001", "call_status": "DISPATCHED",
            "estimated_arrival_seconds": 90,
        })

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HttpDrtClient("http://dispatch.example", client=async_client)
        result = await client.request_call(
            boarding_station_id=3,
            alighting_station_id=9,
            expected_wait_s=300,
            stop_to_stop_travel_s=142.4,
        )
        await async_client.aclose()
        return result

    result = asyncio.run(run())
    assert result.status == "accepted"
    assert captured["body"]["stop_to_stop_travel_seconds"] == 142


def test_out_of_range_estimate_is_clamped_not_replaced():
    """모델이 이상값을 내도(예: 음수·초장시간) 배차 서버 스키마 범위(1~7200초) 안으로
    잘라 보낸다 — 지어낸 값이 아니라 실제 예측값을 보호하는 클램프다."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "call_id": "CALL-1", "vehicle_id": "VEHICLE-001", "call_status": "DISPATCHED",
            "estimated_arrival_seconds": 90,
        })

    async def run():
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HttpDrtClient("http://dispatch.example", client=async_client)
        return await client.request_call(
            boarding_station_id=3,
            alighting_station_id=9,
            expected_wait_s=300,
            stop_to_stop_travel_s=999999,
        )

    asyncio.run(run())
    assert captured["body"]["stop_to_stop_travel_seconds"] == MAX_STOP_TO_STOP_S
    assert MIN_STOP_TO_STOP_S == 1
