from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

# 정류장 shortlist/도보 한도 기본값. app/stations/find_departure_station.py의 알고리즘이
# 실제로 쓰는 상수와 같은 값이며, config는 알고리즘 모듈에 의존하지 않도록 여기 직접 둔다.
DEFAULT_STATION_SHORTLIST_TOP_K = 5
DEFAULT_WALK_LIMIT_M = 500.0


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_origins(value: str | None) -> tuple[str, ...]:
    """CORS 허용 오리진. 기본값에 "null"(file:// 등)을 넣지 않는다.

    로컬 HTML 파일을 직접 열어 테스트해야 한다면 CORS_ORIGINS에 명시적으로
    null을 넣어야 한다. 서버가 페이지를 서빙하는 /api/sender 경로는
    동일 오리진이라 CORS 자체가 필요 없다.
    """
    if not value:
        return ("http://localhost:3000", "http://127.0.0.1:3000")
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


_load_env(BASE_DIR / ".env")


@dataclass(slots=True)
class Settings:
    app_name: str = "DRT 위치 기반 도착지 추천 API"
    app_version: str = "2.0.0"
    # 기본값은 안전한 쪽(운영). 로컬 개발은 .env에서 DEBUG=True로 켠다.
    debug: bool = field(default_factory=lambda: _as_bool(os.getenv("DEBUG"), False))
    database_path: Path = field(
        default_factory=lambda: Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "db.sqlite3")))
    )
    stations_csv_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("STATIONS_CSV_PATH", str(BASE_DIR / "data" / "stations_geo.csv"))
        )
    )
    web_dir: Path = field(default_factory=lambda: BASE_DIR / "web")
    tmap_app_key: str = field(default_factory=lambda: os.getenv("TMAP_APP_KEY", "").strip())
    tmap_base_url: str = "https://apis.openapi.sk.com"
    tmap_timeout_s: float = field(default_factory=lambda: float(os.getenv("TMAP_TIMEOUT_S", "8")))
    tmap_max_retries: int = field(default_factory=lambda: int(os.getenv("TMAP_MAX_RETRIES", "2")))
    relay_api_token: str = field(default_factory=lambda: os.getenv("RELAY_API_TOKEN", "").strip())
    cors_origins: tuple[str, ...] = field(default_factory=lambda: _as_origins(os.getenv("CORS_ORIGINS")))
    # GPS 오차 허용 한도(m). 실내/PC 브라우저의 WiFi 기반 위치는 수백m 이상
    # 오차가 흔하므로, 로컬 테스트에서는 .env로 개인만 완화할 수 있다.
    max_location_accuracy_m: float = field(
        default_factory=lambda: float(os.getenv("MAX_LOCATION_ACCURACY_M", "100"))
    )
    max_location_age_s: int = 120
    # 요청에 max_walk_m이 없을 때 적용할 기본 도보 한도(m).
    default_max_walk_m: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_MAX_WALK_M", DEFAULT_WALK_LIMIT_M))
    )
    # 보행 경로 API를 호출할 후보 정류장 수 상한. 0 이하면 상한 없음.
    station_shortlist_top_k: int = field(
        default_factory=lambda: int(os.getenv("STATION_SHORTLIST_TOP_K", DEFAULT_STATION_SHORTLIST_TOP_K))
    )
    # 가상 DRT 서버(mock-drt-server) 주소. 비어 있으면 MockDrtClient로 동작한다
    # (배차 서버 없이 항상 수락). 값이 있으면 실제 배차·차량추적·조회링크가 연동된다.
    drt_server_base_url: str = field(
        default_factory=lambda: os.getenv("DRT_SERVER_BASE_URL", "").strip().rstrip("/")
    )
    drt_server_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("DRT_SERVER_TIMEOUT_S", "5"))
    )
    # 정류장 간 DRT 차량 소요시간 예측 모델(app/travel_time/models/*.joblib) 디렉터리.
    # 없거나 로드 실패해도 예측기가 공식/규칙 폴백으로 안전하게 동작한다.
    eta_artifacts_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("ETA_ARTIFACTS_DIR", str(BASE_DIR / "app" / "travel_time" / "models"))
        )
    )

    def __post_init__(self) -> None:
        # 인증 없이 공개되면 TMAP 쿼터가 무단 소모되므로 운영 모드에서는 기동을 막는다.
        if not self.debug and not self.relay_api_token:
            raise RuntimeError(
                "운영 모드(DEBUG=False)에서는 RELAY_API_TOKEN이 필요합니다. "
                ".env에 값을 설정하거나, 로컬 개발이라면 DEBUG=True로 두세요."
            )

    @property
    def shortlist_top_k(self) -> int | None:
        return self.station_shortlist_top_k if self.station_shortlist_top_k > 0 else None

    @property
    def use_real_api(self) -> bool:
        return bool(self.tmap_app_key)


settings = Settings()
