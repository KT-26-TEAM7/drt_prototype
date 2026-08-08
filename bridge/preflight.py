"""세 프로세스가 제대로 물려 있는지 확인한다.

포트를 잘못 두면 조회 링크가 엉뚱한 서버를 가리키는데, 그 증상이 **어르신이 문자를
받아 눌러 본 뒤에야** 드러난다. 데모 전에 여기서 먼저 잡는다.

표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse, urlsplit

# 조회 대시보드는 토큰이 무엇이든 HTML을 돌려준다(api/tracking.py가 토큰을 보지 않는다).
# 그래서 배차 서버가 그 주소에서 서비스 중인지 예약 없이도 확인할 수 있다.
_PROBE_TOKEN = "preflight-probe"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def _get(url: str, token: str = "", timeout: float = 5.0) -> tuple[int, bytes]:
    headers = {"Accept": "*/*"}
    if token:
        headers["X-Relay-Token"] = token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def same_origin(first: str, second: str) -> bool:
    """호스트와 포트가 같은 주소인지. localhost와 127.0.0.1은 같은 것으로 본다."""
    def key(url: str) -> tuple[str, int]:
        parsed = urlparse(url if "//" in url else f"http://{url}")
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            host = "localhost"
        return host, parsed.port or (443 if parsed.scheme == "https" else 80)

    return key(first) == key(second)


def check_dispatch_server(dispatch_url: str) -> CheckResult:
    name = "배차 서버 응답"
    try:
        status, body = _get(f"{dispatch_url}/vehicles")
    except urllib.error.URLError as error:
        return CheckResult(name, False, f"{dispatch_url}에 붙지 못했습니다 ({error.reason})",
                           "mock-drt-server를 먼저 띄우세요.")
    if status != 200:
        return CheckResult(name, False, f"{dispatch_url}/vehicles 가 {status}를 돌려줬습니다",
                           "그 주소가 정말 배차 서버인지 확인하세요.")
    try:
        vehicles = json.loads(body)
    except ValueError:
        return CheckResult(name, False, "차량 목록이 JSON이 아닙니다",
                           "그 포트에 다른 서버가 떠 있을 수 있습니다.")
    available = sum(1 for v in vehicles if v.get("status") == "AVAILABLE")
    return CheckResult(name, True, f"차량 {len(vehicles)}대 (배차 가능 {available}대)")


def check_drt_service(drt_url: str, token: str = "") -> CheckResult:
    name = "drt_service 응답"
    try:
        status, body = _get(f"{drt_url}/", token)
    except urllib.error.URLError as error:
        return CheckResult(name, False, f"{drt_url}에 붙지 못했습니다 ({error.reason})",
                           "drt_service를 먼저 띄우세요.")
    if status != 200:
        return CheckResult(name, False, f"{drt_url}/ 가 {status}를 돌려줬습니다")
    try:
        root = json.loads(body)
    except ValueError:
        return CheckResult(name, False, "응답이 JSON이 아닙니다",
                           "그 포트에 배차 서버가 떠 있는 건 아닌지 확인하세요.")
    if "service" not in root:
        return CheckResult(name, False, "drt_service가 아닌 것 같습니다",
                           "포트를 서로 바꿔 띄우지 않았는지 확인하세요.")
    return CheckResult(name, True, f"{root.get('service')} (provider={root.get('provider')})")


def check_ports_not_shared(drt_url: str, dispatch_url: str) -> CheckResult:
    name = "포트 분리"
    if same_origin(drt_url, dispatch_url):
        return CheckResult(
            name, False, f"두 서버가 같은 주소({drt_url})로 설정되어 있습니다",
            "배차 서버를 8000, drt_service를 8001로 두세요.",
        )
    return CheckResult(name, True, f"drt_service={drt_url} / 배차={dispatch_url}")


def check_dispatch_wired(drt_url: str, token: str = "") -> CheckResult:
    """drt_service가 MOCK이 아니라 실제 배차 서버를 보고 있는지."""
    name = "배차 연동 설정"
    try:
        _, body = _get(f"{drt_url}/", token)
        root = json.loads(body)
    except (urllib.error.URLError, ValueError):
        return CheckResult(name, False, "drt_service 상태를 읽지 못했습니다")
    if root.get("dispatch") != "drt_server":
        return CheckResult(
            name, False, "drt_service가 MOCK 배차로 동작 중입니다",
            "drt_service의 DRT_SERVER_BASE_URL을 배차 서버 주소로 설정하세요.",
        )
    return CheckResult(name, True, "drt_service -> 배차 서버 연결됨")


def check_relay_auth(drt_url: str, token: str = "") -> CheckResult:
    """인증이 필요한 경로에 실제로 들어갈 수 있는지.

    drt_service의 .env에 RELAY_API_TOKEN이 있으면 모든 /api/* 호출에 헤더가 필요하다.
    이걸 예약을 넣어 볼 때가 되어서야 발견하면 늦다.
    """
    name = "릴레이 토큰"
    try:
        status, _ = _get(f"{drt_url}/api/stations", token)
    except urllib.error.URLError as error:
        return CheckResult(name, False, f"확인하지 못했습니다 ({error.reason})")
    if status == 401:
        return CheckResult(
            name, False, "인증에 실패했습니다(401)",
            "drt_service의 .env에 RELAY_API_TOKEN이 설정돼 있습니다. "
            "같은 값을 --token으로 넘기거나 RELAY_API_TOKEN 환경변수에 넣으세요.",
        )
    if status != 200:
        return CheckResult(name, False, f"/api/stations가 {status}를 돌려줬습니다")
    return CheckResult(name, True, "인증 통과" if token else "토큰 없이 접근 가능(DEBUG 모드)")


def check_tracking_origin(dispatch_url: str) -> CheckResult:
    """조회 링크가 만들어질 주소에서 실제로 대시보드가 서비스되는지.

    예약을 만들지 않고 확인한다. 배차 서버의 대시보드는 토큰을 검사하지 않고
    HTML을 돌려주므로, 아무 토큰이나 넣어 보면 그 주소의 정체를 알 수 있다.
    """
    name = "조회 대시보드 서비스"
    url = f"{dispatch_url}/tracking/{_PROBE_TOKEN}"
    try:
        status, body = _get(url)
    except urllib.error.URLError as error:
        return CheckResult(name, False, f"{url}에 붙지 못했습니다 ({error.reason})")
    if status != 200 or b"<" not in body[:200]:
        return CheckResult(
            name, False, f"{url}가 대시보드를 돌려주지 않습니다(status={status})",
            "배차 서버의 TRACKING_BASE_URL이 실제 리슨 포트와 다른지 확인하세요.",
        )
    return CheckResult(name, True, f"{dispatch_url}/tracking/... 에서 대시보드 확인")


def run_checks(drt_url: str, dispatch_url: str, token: str = "") -> list[CheckResult]:
    """예약을 만들지 않는 점검들. 데모 직전에 돌리기 좋다."""
    return [
        check_ports_not_shared(drt_url, dispatch_url),
        check_dispatch_server(dispatch_url),
        check_drt_service(drt_url, token),
        check_relay_auth(drt_url, token),
        check_dispatch_wired(drt_url, token),
        check_tracking_origin(dispatch_url),
    ]


def uses_real_tmap(drt_url: str, token: str = "") -> bool:
    """drt_service가 실제 TMAP을 쓰는 중인지. 쿼터를 소모하는 점검 전에 확인한다."""
    try:
        _, body = _get(f"{drt_url}/", token)
        return json.loads(body).get("provider") == "tmap"
    except (urllib.error.URLError, ValueError):
        return False


def tracking_status_url(tracking_url: str) -> str:
    """대시보드 링크(`{base}?token=...`)에서 JSON 상태 API 주소를 만든다.

    링크는 사람이 여는 화면 주소이지 API 주소가 아니다. 토큰은 경로가 아니라
    쿼리스트링으로 오므로(`app/services/tracking_token.py`의 `build_tracking_url`),
    `f"{tracking_url}/status"`처럼 이어 붙이면 `?token=...` 뒤에 `/status`가 붙어
    깨진다. 토큰을 뽑아 배차 서버의 `/tracking/{token}/status`로 다시 구성한다.
    """
    parsed = urlsplit(tracking_url)
    tokens = parse_qs(parsed.query).get("token")
    if not tokens:
        raise ValueError(f"조회 링크에 token 쿼리스트링이 없습니다: {tracking_url}")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}/tracking/{tokens[0]}/status"


def tracking_url_warning(tracking_url: str, drt_base_url: str) -> str:
    """배차 서버가 준 조회 링크가 drt_service를 가리키면 경고를 돌려준다.

    이건 명백한 설정 오류다 — drt_service에는 그런 경로가 없어서 어르신이 문자를
    눌러도 아무것도 나오지 않는다. 반대로 링크 호스트가 배차 서버와 달라도
    역방향 프록시나 공개 도메인을 쓰는 정상적인 경우가 있으므로 그건 경고하지 않는다.
    """
    if not tracking_url or not drt_base_url:
        return ""
    if same_origin(tracking_url, drt_base_url):
        return "tracking_url_points_to_drt_service"
    return ""
