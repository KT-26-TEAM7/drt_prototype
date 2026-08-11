"""실행 중인 drt-algo 서버의 health와 계획 API를 확인한다.

환경변수의 DRT_BACKEND_URL/DRT_RELAY_TOKEN을 사용하며 실제 예약은 만들지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from dotenv import load_dotenv

load_dotenv()

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.backend import DRTBackendClient, interpret_plan
from carecall_drt.config import Settings
from carecall_drt.schemas import Location, SessionState


def main() -> None:
    settings = Settings(gemini_policy="off")
    state = SessionState(location=Location(37.4849, 126.9710, 15))
    analyzer = DRTAnalyzer(settings)
    analysis = analyzer.analyze_turn(
        "오늘 오후 3시에 가까운 정형외과로 집 앞에서 이동 차량 예약해줘",
        state,
        allow_internal_gemini=False,
    )
    client = DRTBackendClient(settings)
    try:
        print("[health]")
        print(json.dumps(client.health(), ensure_ascii=False, indent=2))
        print("\n[plan]")
        plan, request = client.plan(analysis, state)
        print("request:", json.dumps(request, ensure_ascii=False, indent=2))
        print("response:", json.dumps(plan, ensure_ascii=False, indent=2))
        print("guide:", interpret_plan(plan).message)
    finally:
        client.close()


if __name__ == "__main__":
    main()
