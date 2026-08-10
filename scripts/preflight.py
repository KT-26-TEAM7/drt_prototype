"""이미 떠 있는 스택이 제대로 물려 있는지 점검한다.

특히 **조회 링크가 정말 배차 서버를 가리키는지**를 본다. 이게 어긋나면 어르신이
문자를 받아 링크를 눌러 봐야 문제가 드러나기 때문이다.

    py scripts/preflight.py
    py scripts/preflight.py --full     # 실제로 예약을 한 건 넣어 링크까지 확인
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge import preflight  # noqa: E402
from bridge.config import settings  # noqa: E402


def _post_json(url: str, payload: dict, token: str) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["X-Relay-Token"] = token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, {"detail": error.read().decode("utf-8", errors="replace")[:200]}


def check_real_booking(drt_url: str, dispatch_url: str, token: str) -> list[preflight.CheckResult]:
    """예약을 한 건 실제로 넣어, 돌아온 조회 링크가 열리는지까지 확인한다.

    **차량이 실제로 배차된다.** 배차 서버 차량이 2대뿐이라 연속으로 여러 번
    돌리면 가용 차량이 없어질 수 있다(운행이 끝나면 다시 돌아온다).
    """
    results: list[preflight.CheckResult] = []
    status, body = _post_json(
        f"{drt_url}/api/reservations",
        # 사당솔밭도서관은 실제 TMAP에서도 이름이 유일하게 잡힌다. "남현서울정형외과"는
        # 실제 TMAP에서 "서울정형외과의원" 등 비슷한 이름의 병원이 여러 곳 검색되어
        # needs_destination_confirmation으로 멈추는 경우가 있어 점검용으로는 부적절하다.
        {"latitude": 37.4849, "longitude": 126.9710,
         "query": "사당솔밭도서관", "is_specific": True},
        token,
    )
    if status != 200:
        results.append(preflight.CheckResult(
            "실제 예약", False, f"예약 요청이 {status}로 실패했습니다: {body}",
        ))
        return results

    reservation = body.get("reservation")
    if not reservation:
        reason = body.get("reason") or ""
        if "확정할 수 없는" in reason:
            hint = "목적지 후보가 여러 곳이거나 검색되지 않았을 수 있습니다. TMAP_APP_KEY 설정과 검색어를 확인하세요."
        else:
            hint = "배차 서버에 가용 차량이 있는지 확인하세요."
        results.append(preflight.CheckResult(
            "실제 예약", False, f"예약이 만들어지지 않았습니다: {reason}", hint,
        ))
        return results

    results.append(preflight.CheckResult(
        "실제 예약", True,
        f"{reservation['call_id']} · 차량 {reservation.get('vehicle_id')}"
        f" · 도착예정 {reservation.get('estimated_arrival_s')}초",
    ))

    tracking_url = reservation.get("tracking_url") or ""
    if not tracking_url:
        results.append(preflight.CheckResult(
            "조회 링크 발급", False, "tracking_url이 비어 있습니다",
            "drt_service가 MOCK 배차로 동작 중일 수 있습니다.",
        ))
        return results

    # 이게 핵심이다. 문자로 나갈 바로 그 주소를 실제로 열어 본다.
    warning = preflight.tracking_url_warning(tracking_url, drt_url)
    if warning:
        results.append(preflight.CheckResult(
            "발급된 조회 링크", False,
            f"조회 링크가 drt_service를 가리킵니다: {tracking_url}",
            "배차 서버의 TRACKING_BASE_URL이 잘못됐습니다. run_stack.py로 띄우면 자동으로 맞춰집니다.",
        ))
        return results

    try:
        status_url = preflight.tracking_status_url(tracking_url)
    except ValueError as error:
        results.append(preflight.CheckResult(
            "발급된 조회 링크", False, str(error),
            "app/services/tracking_token.py의 build_tracking_url이 바뀌었는지 확인하세요.",
        ))
        return results

    try:
        code, payload = preflight._get(status_url)
    except urllib.error.URLError as error:
        results.append(preflight.CheckResult(
            "발급된 조회 링크", False, f"{tracking_url}에 붙지 못했습니다 ({error.reason})",
            "문자로 나갈 링크가 열리지 않는 상태입니다.",
        ))
        return results

    if code != 200:
        results.append(preflight.CheckResult(
            "발급된 조회 링크", False, f"조회 링크가 {code}를 돌려줍니다",
            "TRACKING_BASE_URL과 실제 리슨 포트가 다른지 확인하세요.",
        ))
        return results

    tracking = json.loads(payload)
    results.append(preflight.CheckResult(
        "발급된 조회 링크", True,
        f"열림 · {tracking['status']} · {tracking['vehicle']['display_name']}"
        f" · 도착까지 {tracking['estimated_arrival_seconds']}초\n"
        f"         브라우저로 직접 열어보려면: {tracking_url}",
    ))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="케어콜-DRT-배차 스택 사전 점검")
    parser.add_argument("--drt-service", default=settings.drt_base_url)
    parser.add_argument("--dispatch", default=settings.dispatch_base_url)
    parser.add_argument("--token", default=settings.relay_api_token)
    parser.add_argument("--full", action="store_true",
                        help="예약을 실제로 넣어 조회 링크까지 확인(차량이 배차됨)")
    args = parser.parse_args()

    print(f"drt_service : {args.drt_service}")
    print(f"배차 서버   : {args.dispatch}")
    print()

    results = preflight.run_checks(args.drt_service, args.dispatch, args.token)
    if args.full and all(result.ok for result in results):
        if preflight.uses_real_tmap(args.drt_service, args.token):
            # 이 점검은 예약을 실제로 넣으므로 TMAP 호출이 발생한다.
            print("주의: drt_service가 실제 TMAP을 쓰고 있어 이 점검이 쿼터를 소모합니다.")
            print()
        results += check_real_booking(args.drt_service, args.dispatch, args.token)

    print("점검 결과")
    print("-" * 64)
    for result in results:
        print(f"  [{'OK  ' if result.ok else '실패'}] {result.name}: {result.detail}")
        if not result.ok and result.hint:
            print(f"         -> {result.hint}")
    print("-" * 64)

    ok = all(result.ok for result in results)
    if ok and not args.full:
        print("  정상입니다. 조회 링크까지 확인하려면 --full을 붙이세요.")
    elif ok:
        print("  정상입니다. 문자로 나갈 링크까지 열리는 것을 확인했습니다.")
    else:
        print("  문제가 있습니다. 위 안내를 확인하세요.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
