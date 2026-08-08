"""DRT 배차 클라이언트.

`MockDrtClient`는 배차 서버 없이 항상 수락하는 자리표시자이고, `HttpDrtClient`는
팀의 가상 DRT 서버(mock-drt-server)의 REST API를 호출한다. 어느 쪽을 쓸지는
`app/main.py`가 설정(`DRT_SERVER_BASE_URL`)으로 고른다 — 값이 비어 있으면 MOCK이다.

정류장 ID 체계는 양쪽이 같다. 배차 서버의 `data/stops.csv`가 이 서비스의
`data/stations_geo.csv`와 동일한 파일이라, `station_id`를 문자열로 바꾸기만 하면
그대로 통한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

# 배차 서버 CallCreateRequest.stop_to_stop_travel_seconds의 허용 범위. 서버 스키마와 같아야 한다.
MIN_STOP_TO_STOP_S = 1
MAX_STOP_TO_STOP_S = 7200


@dataclass(frozen=True)
class DrtCallResult:
    call_id: str
    status: str  # "accepted" | "rejected"
    requested_at: str
    # 아래는 배차 서버가 함께 주는 정보다. MockDrtClient에서는 비어 있다.
    vehicle_id: str | None = None
    # 차량이 승차 정류장에 닿기까지 걸리는 시간. 요청의 expected_wait_s(추정 대기시간)를
    # 대체하는 실제 계산값이다.
    estimated_arrival_s: int | None = None
    tracking_url: str | None = None
    tracking_message: str | None = None
    dispatch_status: str | None = None  # 배차 서버 원본 상태(DISPATCHED 등)
    reason: str | None = None


class DrtClient(Protocol):
    async def request_call(
        self,
        boarding_station_id: int,
        alighting_station_id: int,
        expected_wait_s: float,
        stop_to_stop_travel_s: float | None = None,
    ) -> DrtCallResult: ...

    async def close(self) -> None: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockDrtClient:
    """배차 서버 없이 항상 수락한다. 로컬 개발·테스트용."""

    async def request_call(
        self,
        boarding_station_id: int,
        alighting_station_id: int,
        expected_wait_s: float,
        stop_to_stop_travel_s: float | None = None,
    ) -> DrtCallResult:
        return DrtCallResult(
            call_id=uuid.uuid4().hex[:12],
            status="accepted",
            requested_at=_now_iso(),
        )

    async def close(self) -> None:
        return None


class HttpDrtClient:
    """가상 DRT 서버(mock-drt-server)의 `POST /calls`를 호출한다.

    배차 서버는 차량을 배정하고, 승차 정류장까지의 도착예정시간과 실시간 조회
    링크(문자로 보낼 문구 포함)를 함께 돌려준다.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:200]
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])
        return response.text[:200]

    @staticmethod
    def _travel_seconds(stop_to_stop_travel_s: float | None) -> int:
        """ETA 모델이 예측한 정류장 간 주행시간을 배차 서버가 받는 범위로 맞춘다.

        값 자체는 항상 호출측(plan_route.py -> confirm_reservation.py)이 ETA
        회귀/분류 모델(app/travel_time/estimate_duration.py)로 미리 계산해 넘겨야
        한다 — 배차 서버가 임의의 기본값으로 운행 구간을 만들면 실제로는 몇 분
        걸리는 이동이 지도에서 1초 만에 끝난 것처럼 보이는 등 시뮬레이션이 조용히
        틀려진다. 그래서 값이 없을 때는 안전한 기본값으로 채우지 않고 예외를
        던져 `request_call`이 배차 자체를 거절하게 한다.

        범위를 벗어난 값(모델의 이상값)만 배차 서버 스키마(1~7200초)에 맞게 자른다
        — 이건 실제로 계산된 값을 보호하는 것이지 없는 값을 지어내는 게 아니다.
        """
        if stop_to_stop_travel_s is None:
            raise ValueError(
                "stop_to_stop_travel_s가 없습니다. ETA 모델이 정류장 간 소요시간을 "
                "계산하지 못한 상태로는 배차를 요청할 수 없습니다."
            )
        seconds = int(round(float(stop_to_stop_travel_s)))
        return max(MIN_STOP_TO_STOP_S, min(MAX_STOP_TO_STOP_S, seconds))

    async def request_call(
        self,
        boarding_station_id: int,
        alighting_station_id: int,
        expected_wait_s: float,
        stop_to_stop_travel_s: float | None = None,
    ) -> DrtCallResult:
        # expected_wait_s는 쓰지 않는다. 그건 요청 측의 추정값이고, 실제 대기시간은
        # 배차 서버가 배정된 차량 위치로 계산해 estimated_arrival_s로 돌려준다.
        requested_at = _now_iso()
        try:
            travel_seconds = self._travel_seconds(stop_to_stop_travel_s)
        except ValueError as exc:
            # 배차 서버에 값을 지어내 보내는 대신, 여기서 거절로 끝낸다(요청 자체를
            # 만들지 않으므로 HTTP 호출도 나가지 않는다).
            return DrtCallResult(call_id="", status="rejected", requested_at=requested_at, reason=str(exc))
        payload: dict[str, Any] = {
            "departure_stop_id": str(boarding_station_id),
            "arrival_stop_id": str(alighting_station_id),
            "stop_to_stop_travel_seconds": travel_seconds,
        }

        try:
            response = await self._client.post(f"{self.base_url}/calls", json=payload)
        except httpx.HTTPError as exc:
            return DrtCallResult(
                call_id="", status="rejected", requested_at=requested_at,
                reason=f"배차 서버 호출 실패: {type(exc).__name__}: {exc}",
            )

        if response.status_code >= 400:
            # 409는 가용 차량 없음. 그 밖은 정류장 ID 오류 등 요청 문제다.
            return DrtCallResult(
                call_id="", status="rejected", requested_at=requested_at,
                reason=self._detail(response),
            )

        try:
            body = response.json()
        except ValueError:
            return DrtCallResult(
                call_id="", status="rejected", requested_at=requested_at,
                reason="배차 서버 응답이 올바른 JSON이 아닙니다.",
            )

        return DrtCallResult(
            call_id=str(body.get("call_id") or ""),
            status="accepted",
            requested_at=requested_at,
            vehicle_id=body.get("vehicle_id"),
            estimated_arrival_s=body.get("estimated_arrival_seconds"),
            tracking_url=body.get("tracking_url"),
            tracking_message=body.get("tracking_message"),
            dispatch_status=body.get("call_status"),
        )
