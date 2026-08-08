"""배차 연동이 실제로 이어지는지 두 서버에 붙어 확인한다.

케어콜 브릿지가 없어도 돌아간다. drt_service -> 가상 DRT 서버 -> 조회 링크까지의
연결만 따로 떼어 검증하는 용도다. 표준 라이브러리만 쓰므로 설치 없이 실행된다.

    # 터미널 1: 배차 서버 (8000)
    cd mock-drt-server-main && .venv/Scripts/python.exe scripts/run_server.py

    # 터미널 2: drt_service (8001)
    cd drt_service
    set DRT_SERVER_BASE_URL=http://127.0.0.1:8000
    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8001

    # 터미널 3
    py scripts/verify_dispatch.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.preflight import tracking_status_url  # noqa: E402

DEFAULT_DRT_SERVICE = "http://127.0.0.1:8001"
DEFAULT_DISPATCH = "http://127.0.0.1:8000"


def request_json(url: str, payload: dict | None = None, token: str = "") -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Relay-Token"] = token

    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, {"detail": body[:300]}
    except urllib.error.URLError as error:
        raise SystemExit(f"서버에 붙지 못했습니다: {url}\n  {error.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="drt_service <-> 가상 DRT 서버 연동 확인")
    parser.add_argument("--drt-service", default=DEFAULT_DRT_SERVICE)
    parser.add_argument("--dispatch", default=DEFAULT_DISPATCH)
    parser.add_argument("--token", default=os.getenv("RELAY_API_TOKEN", ""),
                        help="drt_service의 RELAY_API_TOKEN (기본값은 같은 이름의 환경변수)")
    parser.add_argument("--query", default="남현서울정형외과")
    parser.add_argument("--latitude", type=float, default=37.4849)
    parser.add_argument("--longitude", type=float, default=126.9710)
    parser.add_argument("--polls", type=int, default=3, help="호출 상태를 몇 번 확인할지")
    args = parser.parse_args()

    print("=" * 68)
    print("1) 두 서버 상태")
    print("=" * 68)
    _, root = request_json(f"{args.drt_service}/", token=args.token)
    print(f"  drt_service : provider={root.get('provider')} dispatch={root.get('dispatch')}")
    if root.get("dispatch") != "drt_server":
        print("  ! DRT_SERVER_BASE_URL이 설정되지 않아 MOCK 배차로 동작 중입니다.")
    _, vehicles = request_json(f"{args.dispatch}/vehicles")
    print(f"  배차 서버   : 차량 {len(vehicles)}대")
    for vehicle in vehicles:
        print(f"      {vehicle['vehicle_id']} {vehicle['status']} (근처 정류장 {vehicle['nearest_stop_id']})")

    print()
    print("=" * 68)
    print(f"2) 예약 요청  query={args.query!r}")
    print("=" * 68)
    status_code, body = request_json(
        f"{args.drt_service}/api/reservations",
        {
            "latitude": args.latitude,
            "longitude": args.longitude,
            "query": args.query,
            "is_specific": True,
        },
        token=args.token,
    )
    if status_code != 200:
        raise SystemExit(f"예약 실패({status_code}): {body}")

    plan = body.get("plan") or {}
    reservation = body.get("reservation")
    print(f"  계획 상태   : {plan.get('status')} / 추천={plan.get('recommended_mode')}")
    print(f"  승차 정류장 : {(plan.get('boarding') or {}).get('name')}"
          f" (id={(plan.get('boarding') or {}).get('station_id')})")
    print(f"  하차 정류장 : {(plan.get('alighting') or {}).get('name')}"
          f" (id={(plan.get('alighting') or {}).get('station_id')})")
    print(f"  차량 구간   : {(plan.get('vehicle') or {}).get('duration_s')}초"
          f" (출처 {(plan.get('vehicle') or {}).get('source')})")

    if not reservation:
        raise SystemExit(f"  예약이 만들어지지 않았습니다: {body.get('reason')}")

    print()
    print("  --- 배차 서버가 돌려준 값 ---")
    print(f"  호출 번호   : {reservation['call_id']}")
    print(f"  배정 차량   : {reservation.get('vehicle_id')}")
    print(f"  도착 예정   : {reservation.get('estimated_arrival_s')}초")
    print(f"  배차 상태   : {reservation.get('dispatch_status')}")
    print(f"  조회 링크   : {reservation.get('tracking_url')}")
    print()
    print("  --- 문자로 나갈 문구 ---")
    for line in (reservation.get("tracking_message") or "").splitlines():
        print(f"    {line}")

    tracking_url = reservation.get("tracking_url")
    if not tracking_url:
        raise SystemExit("조회 링크가 없습니다. 배차 서버 연동을 확인하세요.")

    print()
    print("=" * 68)
    print("3) 조회 링크로 실시간 상태 확인")
    print("=" * 68)
    status_url = tracking_status_url(tracking_url)
    for attempt in range(1, args.polls + 1):
        code, tracking = request_json(status_url)
        if code != 200:
            print(f"  [{attempt}] 조회 실패({code}): {tracking}")
            break
        vehicle = tracking["vehicle"]
        print(f"  [{attempt}] {tracking['status']:<12} {tracking['status_message']}")
        print(f"      {vehicle['display_name']} 위치 "
              f"({vehicle['latitude']:.6f}, {vehicle['longitude']:.6f})"
              f" · 도착까지 {tracking['estimated_arrival_seconds']}초"
              f" · 경로점 {len(tracking['route']['coordinates'])}개({tracking['route']['source']})")
        if attempt < args.polls:
            time.sleep(3)

    print()
    print("확인 완료. 지도 화면은 브라우저에서 아래 주소로 볼 수 있습니다.")
    print(f"  {tracking_url}")


if __name__ == "__main__":
    main()
