"""저장된 케어콜 분석 결과(JSON)를 DRT로 넘겨 보는 실행 스크립트.

오프라인(가짜 서버)으로 전체 분기를 확인하거나, 실제로 떠 있는 drt_service에
그대로 붙여 볼 수 있다.

    # 샘플 전부를 가짜 서버로 실행 (drt_service·네트워크 불필요)
    py scripts/run_handoff.py --all --offline

    # 한 건만, 되물음에 대한 답까지 이어서
    py scripts/run_handoff.py samples/01_nearby_market_ready.json --offline --reply "응 불러줘"

    # 실제 drt_service에 붙이기 (.env의 DRT_BASE_URL, RELAY_API_TOKEN 사용)
    py scripts/run_handoff.py samples/01_nearby_market_ready.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bridge.drt_client import DrtServiceClient  # noqa: E402
from bridge.fake_service import FakeDrtService  # noqa: E402
from bridge.orchestrator import DrtHandoff, HandoffOutcome  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]


def _print_outcome(outcome: HandoffOutcome) -> None:
    print(f"  결정   : {outcome.action} ({outcome.code})")
    if outcome.drt_request:
        query = outcome.drt_request.get("query")
        is_specific = outcome.drt_request.get("is_specific")
        종류 = "정확명" if is_specific else "대분류"
        print(f"  DRT요청: query={query!r} ({종류} 검색)")
    if outcome.text:
        print(f"  다솜이 : {outcome.text}")
    if outcome.expects:
        print(f"  기다림 : {outcome.expects}")
    if outcome.guardian_message:
        print(f"  보호자 : {outcome.guardian_message}")
    for note in outcome.notes:
        print(f"  참고   : {note}")


def run_sample(handoff: DrtHandoff, path: Path, user_id: str, replies: list[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    print()
    print("=" * 72)
    print(f"[{path.name}] {payload.get('_note', '')}")
    print("=" * 72)

    outcome = handoff.handle_analysis(user_id, payload)
    _print_outcome(outcome)

    for reply in replies:
        if not outcome.expects:
            break
        print(f"\n  어르신 : {reply}")
        outcome = handoff.handle_reply(user_id, reply)
        _print_outcome(outcome)


def main() -> None:
    parser = argparse.ArgumentParser(description="케어콜 분석 결과를 DRT로 넘겨 보는 데모")
    parser.add_argument("sample", nargs="?", help="분석 결과 JSON 파일 경로")
    parser.add_argument("--all", action="store_true", help="samples/ 전체 실행")
    parser.add_argument("--user", default="elder_demo_01", help="어르신 프로필 ID")
    parser.add_argument("--offline", action="store_true", help="가짜 DRT 서버 사용")
    parser.add_argument("--reply", action="append", default=[],
                        help="되물음에 대한 답변(여러 번 지정 가능)")
    args = parser.parse_args()

    if not args.sample and not args.all:
        parser.error("샘플 파일을 지정하거나 --all을 쓰세요.")

    service = FakeDrtService() if args.offline else DrtServiceClient()
    handoff = DrtHandoff(service)

    if args.all:
        for path in sorted((PROJECT_DIR / "samples").glob("*.json")):
            run_sample(handoff, path, args.user, args.reply)
    else:
        path = Path(args.sample)
        if not path.is_absolute():
            path = PROJECT_DIR / path
        run_sample(handoff, path, args.user, args.reply)

    print()


if __name__ == "__main__":
    main()
