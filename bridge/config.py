"""브릿지 설정.

drt_service/app/config.py와 같은 방식으로 .env를 직접 읽는다(python-dotenv 의존성 없이).
브릿지 코어는 표준 라이브러리만 쓰고, httpx는 실제 HTTP 호출 시에만 지연 import한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")


@dataclass(slots=True)
class Settings:
    # drt_service가 떠 있는 주소.
    # 배차 서버가 8000을 쓰므로(조회 링크가 그 포트 기준으로 만들어진다) drt_service는 8001에 둔다.
    drt_base_url: str = field(
        default_factory=lambda: os.getenv("DRT_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    )
    # 가상 DRT 서버(mock-drt-server) 주소. 브릿지가 직접 호출하지는 않고,
    # 사전 점검(scripts/preflight.py)과 조회 링크 검증에 쓴다.
    dispatch_base_url: str = field(
        default_factory=lambda: os.getenv("DISPATCH_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    )
    # drt_service의 .env와 같은 값이어야 한다. 비어 있으면 헤더를 붙이지 않는다
    # (drt_service가 DEBUG=True로 토큰 없이 떠 있는 경우).
    relay_api_token: str = field(default_factory=lambda: os.getenv("RELAY_API_TOKEN", "").strip())
    timeout_s: float = field(default_factory=lambda: float(os.getenv("DRT_TIMEOUT_S", "15")))

    # 어르신 프로필의 등록 좌표는 실측 GPS가 아니다. drt_service는 accuracy가
    # MAX_LOCATION_ACCURACY_M(기본 100m)을 넘으면 422로 거절하므로, 등록 주소
    # 수준의 정밀도를 명시적으로 표기해 보낸다. 실제 단말 GPS를 쓸 수 있게 되면
    # 이 값 대신 단말이 준 accuracy를 그대로 넘기면 된다.
    profile_accuracy_m: float = field(
        default_factory=lambda: float(os.getenv("PROFILE_ACCURACY_M", "30"))
    )
    # drt_service PlanRequest.expected_wait_s 기본값과 맞춘다.
    expected_wait_s: float = field(
        default_factory=lambda: float(os.getenv("EXPECTED_WAIT_S", "300"))
    )
    # 음성으로 한 번에 읽어 줄 후보 개수. 전화로 듣는 어르신이 기억할 수 있는 수준으로 제한한다.
    max_spoken_candidates: int = field(
        default_factory=lambda: int(os.getenv("MAX_SPOKEN_CANDIDATES", "3"))
    )

    profiles_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("PROFILES_PATH", str(BASE_DIR / "data" / "user_profiles.json"))
        )
    )
    # 어떤 발화가 어떤 DRT 요청으로 넘어갔는지 추적하는 감사 로그.
    # 개인정보가 포함되므로 저장소에 커밋하지 않는다(.gitignore).
    audit_log_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("AUDIT_LOG_PATH", str(BASE_DIR / "data" / "handoff_log.jsonl"))
        )
    )
    # 보낼 문자 내용 기록. 실제 발송 게이트웨이가 붙기 전까지는 여기에만 쌓인다.
    sms_log_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("SMS_LOG_PATH", str(BASE_DIR / "data" / "sent_sms.jsonl"))
        )
    )


settings = Settings()
