"""배포 시 사고를 막는 설정 가드 테스트."""
from __future__ import annotations

import pytest

from app.config import Settings


def test_production_requires_relay_token():
    """인증 없이 공개되면 TMAP 쿼터가 무단 소모되므로 기동을 막는다."""
    with pytest.raises(RuntimeError, match="RELAY_API_TOKEN"):
        Settings(debug=False, relay_api_token="")


def test_production_boots_with_relay_token():
    settings = Settings(debug=False, relay_api_token="a-token")
    assert settings.relay_api_token == "a-token"


def test_debug_mode_allows_empty_token():
    """로컬 개발은 토큰 없이도 돌아가야 한다."""
    assert Settings(debug=True, relay_api_token="").relay_api_token == ""


def test_debug_defaults_to_off(monkeypatch):
    """DEBUG를 명시하지 않으면 운영 모드로 간주한다(안전한 기본값)."""
    monkeypatch.delenv("DEBUG", raising=False)
    assert Settings(relay_api_token="a-token").debug is False


def test_debug_can_be_enabled_by_env(monkeypatch):
    monkeypatch.setenv("DEBUG", "True")
    assert Settings().debug is True


def test_cors_default_excludes_null_origin(monkeypatch):
    """file://에서 온 요청(null 오리진)을 기본으로 허용하지 않는다."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert "null" not in Settings(relay_api_token="a-token").cors_origins


def test_cors_origins_can_be_set_explicitly(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "null,https://drt.example.com")
    assert Settings(relay_api_token="a-token").cors_origins == ("null", "https://drt.example.com")
