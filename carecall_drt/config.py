"""환경변수 기반 설정.

API 키는 코드에 넣지 않고 ``.env`` 또는 운영 환경변수에서만 읽는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    return float(raw) if raw and raw.strip() else None


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
    )
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    # off | candidate | ambiguous_only
    gemini_policy: str = field(default_factory=lambda: os.getenv("DRT_GEMINI_POLICY", "ambiguous_only"))
    gemini_thinking_level: str = field(
        default_factory=lambda: os.getenv("GEMINI_THINKING_LEVEL", "minimal")
    )
    gemini_timeout_s: float = field(default_factory=lambda: _env_float("GEMINI_TIMEOUT_S", 8.0))

    drt_base_url: str = field(
        default_factory=lambda: os.getenv("DRT_BACKEND_URL", "http://127.0.0.1:8000")
    )
    drt_relay_token: str | None = field(default_factory=lambda: os.getenv("DRT_RELAY_TOKEN"))
    drt_timeout_s: float = field(default_factory=lambda: _env_float("DRT_TIMEOUT_S", 12.0))
    drt_enabled: bool = field(default_factory=lambda: _env_bool("DRT_BACKEND_ENABLED", False))
    default_max_walk_m: float = field(default_factory=lambda: _env_float("DRT_MAX_WALK_M", 500.0))
    default_expected_wait_s: float = field(
        default_factory=lambda: _env_float("DRT_EXPECTED_WAIT_S", 300.0)
    )

    # 발표/로컬 데모 좌표. 비워두면 자동 DRT 계획 호출을 하지 않는다.
    demo_latitude: float | None = field(default_factory=lambda: _optional_float("DRT_DEMO_LAT"))
    demo_longitude: float | None = field(default_factory=lambda: _optional_float("DRT_DEMO_LON"))
    demo_accuracy: float = field(default_factory=lambda: _env_float("DRT_DEMO_ACCURACY", 20.0))

    show_drt_json: bool = field(default_factory=lambda: _env_bool("SHOW_DRT_JSON", True))

    def validate(self) -> None:
        if self.gemini_policy not in {"off", "candidate", "ambiguous_only"}:
            raise ValueError("DRT_GEMINI_POLICY는 off, candidate, ambiguous_only 중 하나여야 합니다.")
        if self.gemini_thinking_level not in {"minimal", "low", "medium", "high"}:
            raise ValueError("GEMINI_THINKING_LEVEL 값이 올바르지 않습니다.")
