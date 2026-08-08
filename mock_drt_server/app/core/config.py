import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _read_string(name: str, default: str, *, allow_empty: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty.")
    return value


def _read_int(name: str, default: int, *, minimum: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def _read_float(name: str, default: float, *, minimum: float) -> float:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


STOPS_CSV_PATH = PROJECT_ROOT / "data" / "stops.csv"
DATABASE_URL = _read_string("DATABASE_URL", "sqlite:///./mock_drt.db")

VEHICLE_COUNT = _read_int("VEHICLE_COUNT", 2, minimum=1)
VEHICLE_SPEED_KMH = _read_float("VEHICLE_SPEED_KMH", 30.0, minimum=0.1)
BACKGROUND_UPDATE_INTERVAL_SECONDS = _read_float(
    "BACKGROUND_UPDATE_INTERVAL_SECONDS",
    1.0,
    minimum=0.1,
)
ARRIVAL_WAIT_SECONDS = _read_int("ARRIVAL_WAIT_SECONDS", 2, minimum=0)

# 서버가 들을 포트. scripts/run_server.py가 실제로 이 값으로 바인딩하고,
# 아래 TRACKING_BASE_URL의 기본값도 여기서 파생된다.
PORT = _read_int("PORT", 8000, minimum=1)

# 사용자가 문자로 받는 조회 링크의 기본 주소.
# 기본값을 PORT에서 만들기 때문에, 포트를 바꿔도 링크가 따라온다.
# 역방향 프록시나 공개 도메인을 쓴다면 이 값을 직접 지정하면 되고, 그때는 그쪽이 우선한다.
TRACKING_BASE_URL = _read_string(
    "TRACKING_BASE_URL",
    f"http://localhost:{PORT}/tracking",
).rstrip("/")
TRACKING_TOKEN_TTL_HOURS = _read_int(
    "TRACKING_TOKEN_TTL_HOURS",
    24,
    minimum=1,
)

TMAP_API_URL = _read_string(
    "TMAP_API_URL",
    "https://apis.openapi.sk.com/tmap/routes",
).rstrip("/")
TMAP_APP_KEY = _read_string("TMAP_APP_KEY", "", allow_empty=True)
TMAP_TIMEOUT_SECONDS = _read_float("TMAP_TIMEOUT_SECONDS", 4.0, minimum=0.1)


def tracking_base_url_warning() -> str:
    """조회 링크 주소가 실제 리슨 포트와 어긋났는지 확인한다.

    이 둘이 어긋나면 예약은 정상으로 보이는데 사용자가 문자 속 링크를 눌러 봐야
    문제가 드러난다. 그래서 기동할 때 미리 알린다.

    링크 호스트가 localhost가 아니면 역방향 프록시나 공개 도메인을 쓰는 정상적인
    경우이므로 확인하지 않는다.
    """
    parsed = urlparse(TRACKING_BASE_URL)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return ""

    link_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if link_port == PORT:
        return ""

    return (
        f"TRACKING_BASE_URL이 {link_port}번 포트를 가리키는데 서버는 {PORT}번으로 뜹니다. "
        f"문자로 나가는 조회 링크가 열리지 않습니다. "
        f"TRACKING_BASE_URL을 지우면 PORT에서 자동으로 만들어집니다."
    )
