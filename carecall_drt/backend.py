"""현재 팀 ``drt-algo`` FastAPI 서버 연동 클라이언트.

연동 원칙
- 목적지/정류장 계획: ``POST /api/plan``
- 사용자 최종 경로 확인 후 예약: ``POST /api/reservations``
- 토큰이 설정된 경우 ``X-Relay-Token`` 헤더 사용

네트워크 호출은 동기식으로 얇게 감싸며, 테스트에서는 ``httpx.MockTransport``를
주입할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .schemas import DRTAnalysis, SessionState


class DRTBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlanInterpretation:
    kind: str
    message: str
    requires_route_confirmation: bool = False


def _unwrap_plan(payload: dict[str, Any]) -> dict[str, Any]:
    plan = payload.get("plan")
    return plan if isinstance(plan, dict) else payload


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("stop_name") or value.get("station_name") or "").strip()
    return str(value or "").strip()


def _total_minutes(plan: dict[str, Any]) -> float | None:
    for key in ("estimated_total_minutes", "total_eta_min", "total_minutes"):
        value = plan.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("total_eta_s", "total_eta_sec", "estimated_total_seconds"):
        value = plan.get(key)
        if isinstance(value, (int, float)):
            return float(value) / 60.0
    eta = plan.get("eta")
    if isinstance(eta, dict):
        seconds = eta.get("total_eta_s") or eta.get("total_seconds")
        if isinstance(seconds, (int, float)):
            return float(seconds) / 60.0
    return None


def interpret_plan(payload: dict[str, Any]) -> PlanInterpretation:
    """서버 버전별 세부 필드 차이를 흡수해 음성 안내용 결과로 바꾼다."""
    plan = _unwrap_plan(payload)
    status = str(plan.get("status") or payload.get("status") or "unknown")
    destination = _name(plan.get("destination"))
    boarding = _name(plan.get("boarding_station") or plan.get("boarding"))
    alighting = _name(plan.get("alighting_station") or plan.get("alighting"))
    minutes = _total_minutes(plan)
    time_text = f" 약 {minutes:.0f}분" if minutes is not None else ""

    if status in {"ready_for_confirmation", "drt_recommended", "ready"}:
        route = ""
        if boarding and alighting:
            route = f" {boarding} 정류장에서 타고 {alighting} 정류장에서 내립니다."
        place = destination or "선택한 목적지"
        return PlanInterpretation(
            kind="drt",
            # "DRT"는 sanitize()가 "이동 차량"으로 치환하지만 단순 문자열 치환이라
            # 조사(로/으로)까지 맞춰 주지 못한다("이동 차량로"). 처음부터 올바른
            # 조사로 쓴다.
            message=f"{place}까지 이동 차량으로 이동할 수 있습니다.{route} 예상 총 이동시간은{time_text or ' 계산 결과를 확인 중입니다'}. 이 경로로 예약할까요?",
            requires_route_confirmation=True,
        )

    if status in {"walk_recommended", "walk"}:
        place = destination or "가장 가까운 목적지"
        return PlanInterpretation(
            kind="walk",
            message=f"{place}은 가까워서 DRT보다 걸어서 이동하는 편이 더 적합합니다.",
        )

    if status == "needs_destination_confirmation":
        candidates = plan.get("candidates")
        names: list[str] = []
        if isinstance(candidates, list):
            for candidate in candidates[:3]:
                name = _name(candidate)
                address = candidate.get("address") if isinstance(candidate, dict) else None
                if name:
                    names.append(f"{name}{f'({address})' if address else ''}")
        joined = ", ".join(names) if names else "검색된 후보"
        return PlanInterpretation(
            kind="destination_confirmation",
            message=f"같은 이름이나 비슷한 장소가 여러 곳 검색되었습니다. {joined} 중 어느 곳인지 알려주세요.",
        )

    if status in {
        "outside_service_area",
        "no_accessible_boarding_station",
        "no_accessible_route",
        "no_route",
    }:
        reason = str(plan.get("reason") or "현재 위치에서는 이용 가능한 DRT 경로를 찾지 못했습니다.")
        return PlanInterpretation(kind="unavailable", message=reason)

    if status in {"route_api_failed", "error"}:
        return PlanInterpretation(
            kind="retry",
            message="경로 조회가 일시적으로 원활하지 않습니다. 잠시 뒤 다시 확인해 주세요.",
        )

    return PlanInterpretation(
        kind="unknown",
        message="경로 계산 결과를 받았지만 안내 형식을 확인하지 못했습니다. 담당자가 결과를 점검해야 합니다.",
    )


def interpret_reservation(payload: dict[str, Any]) -> str:
    """drt_service `/api/reservations` 응답을 안내 문장으로 바꾼다.

    필드명은 실제 응답(`app/reservation/confirm_reservation.py`)과 맞춰야 한다 —
    도착 예정 시간은 `estimated_arrival_s`로 내려온다(`estimated_arrival_seconds`
    아님, 이전 버전은 이 이름 불일치로 조용히 시간 안내를 건너뛰었다).
    `call_id`/`vehicle_id`는 전화로 들으신 어르신이 받아 적을 수 없는 값이라
    말로 읽지 않는다(문자로만 안내, `bridge/notify.py` 참고).
    """
    body = payload.get("reservation") if isinstance(payload.get("reservation"), dict) else payload
    eta = body.get("estimated_arrival_s")
    eta_text = f" 차량은 약 {round(float(eta) / 60)}분 뒤 도착할 예정입니다." if isinstance(eta, (int, float)) else ""
    return f"이동 차량 예약이 접수되었습니다.{eta_text}".strip()


class DRTBackendClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=self.settings.drt_base_url.rstrip("/"),
            timeout=self.settings.drt_timeout_s,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.drt_relay_token:
            headers["X-Relay-Token"] = self.settings.drt_relay_token
        return headers

    def build_plan_request(
        self,
        analysis: DRTAnalysis,
        state: SessionState,
        *,
        weather: str | None = None,
        speed_level: str | None = None,
    ) -> dict[str, Any]:
        if state.location is None:
            raise DRTBackendError("현재 위치가 없어 DRT 계획을 요청할 수 없습니다.")
        if not analysis.route_query:
            raise DRTBackendError("검색할 목적지 정보가 없습니다.")

        payload: dict[str, Any] = {
            "latitude": state.location.latitude,
            "longitude": state.location.longitude,
            "accuracy": state.location.accuracy,
            "captured_at": state.location.captured_at,
            "max_walk_m": self.settings.default_max_walk_m,
            "query": analysis.route_query,
            "is_specific": analysis.is_specific,
            "expected_wait_s": self.settings.default_expected_wait_s,
        }
        if weather:
            payload["weather"] = weather
        if speed_level:
            payload["speed_level"] = speed_level
        return {key: value for key, value in payload.items() if value is not None}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(path, json=payload, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("응답이 JSON 객체가 아닙니다.")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            raise DRTBackendError(f"DRT 백엔드 호출 실패({path}): {exc}") from exc

    def plan(
        self,
        analysis: DRTAnalysis,
        state: SessionState,
        *,
        weather: str | None = None,
        speed_level: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request = self.build_plan_request(analysis, state, weather=weather, speed_level=speed_level)
        return self._post("/api/plan", request), request

    def create_reservation(self, plan_request: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/reservations", plan_request)

    def health(self) -> dict[str, Any]:
        try:
            response = self.client.get("/health", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"status": "unknown"}
        except (httpx.HTTPError, ValueError) as exc:
            raise DRTBackendError(f"DRT 백엔드 상태 확인 실패: {exc}") from exc
