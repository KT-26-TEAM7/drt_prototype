"""drt_service HTTP 클라이언트.

httpx는 이 모듈을 실제로 쓸 때만 import한다. 브릿지의 판단 로직(gate/mapping/speech)은
표준 라이브러리만으로 돌아가야 테스트와 오프라인 데모가 가벼워지기 때문이다.
"""
from __future__ import annotations

from typing import Any, Protocol

from bridge.config import Settings, settings as default_settings


class DrtServiceError(RuntimeError):
    """drt_service 호출 실패."""


class DrtService(Protocol):
    """실제 클라이언트와 가짜 서버가 공유하는 인터페이스."""

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def reserve(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class DrtServiceClient:
    """`POST /api/plan`, `POST /api/reservations`를 호출한다."""

    def __init__(self, config: Settings | None = None, client: Any = None) -> None:
        self.config = config or default_settings
        self._client = client
        self._owns_client = client is None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import httpx
        except ModuleNotFoundError as exc:  # pragma: no cover - 환경 의존
            raise DrtServiceError(
                "httpx가 설치되어 있지 않습니다. `pip install -r requirements.txt`를 실행하거나, "
                "오프라인으로 확인하려면 FakeDrtService를 쓰세요."
            ) from exc
        self._client = httpx.Client(timeout=self.config.timeout_s)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # drt_service가 DEBUG=True로 토큰 없이 떠 있으면 헤더가 필요 없다.
        if self.config.relay_api_token:
            headers["X-Relay-Token"] = self.config.relay_api_token
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        url = f"{self.config.drt_base_url}{path}"
        try:
            response = client.post(url, json=payload, headers=self._headers())
        except Exception as exc:  # httpx.TransportError 등
            raise DrtServiceError(f"{url} 호출 실패: {type(exc).__name__}: {exc}") from exc

        if response.status_code == 401:
            raise DrtServiceError(
                "릴레이 토큰이 올바르지 않습니다. 브릿지 .env의 RELAY_API_TOKEN을 "
                "drt_service의 .env와 같은 값으로 맞추세요."
            )
        if response.status_code == 422:
            # 위치 정확도·시각 검증 실패가 대부분이다.
            raise DrtServiceError(f"요청이 거절되었습니다(422): {response.text[:300]}")
        if response.status_code >= 400:
            raise DrtServiceError(f"{url} 응답 오류({response.status_code}): {response.text[:300]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise DrtServiceError(f"{url} 응답이 올바른 JSON이 아닙니다.") from exc
        if not isinstance(body, dict):
            raise DrtServiceError(f"{url} 응답 최상위 형식이 객체가 아닙니다.")
        return body

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/plan", payload)

    def reserve(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/reservations", payload)

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._client = None
