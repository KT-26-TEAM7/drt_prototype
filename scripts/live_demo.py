"""care-call-bot의 분석기를 직접 불러 한 문장을 끝까지 흘려 보는 데모.

care-call-bot 리포는 브릿지의 의존성이 아니다. 이 스크립트만 예외적으로,
경로를 알려 주면 그쪽 `drt_analyzer.analyze_conversation()`을 불러다 쓴다.
(그쪽은 google-genai·python-dotenv가 필요하고 GEMINI_KEY가 없으면 규칙 기반으로 동작한다.)

    py scripts/live_demo.py "어르신: 가까운 치과에 가려는데 차 좀 불러줘." ^
        --analyzer "C:\\Users\\hyung\\Downloads\\care-call-bot-main\\care-call-bot-main" --offline

`--analyzer`를 생략하면 환경변수 CARE_CALL_BOT_PATH를 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from bridge.drt_client import DrtServiceClient  # noqa: E402
from bridge.fake_service import FakeDrtService  # noqa: E402
from bridge.orchestrator import DrtHandoff  # noqa: E402

# 케어콜 분석기도 이 폴더 안에 함께 있다.
DEFAULT_ANALYZER_DIR = PROJECT_DIR / "care_call_bot"


def load_analyzer(analyzer_dir: str):
    path = Path(analyzer_dir).expanduser()
    if not (path / "drt_analyzer.py").exists():
        raise SystemExit(f"drt_analyzer.py를 찾지 못했습니다: {path}")
    sys.path.insert(0, str(path))
    try:
        import drt_analyzer  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            f"분석기를 불러오지 못했습니다({exc.name} 없음). "
            "care-call-bot 쪽 requirements.txt를 설치한 파이썬으로 실행하세요."
        ) from exc
    return drt_analyzer


def main() -> None:
    parser = argparse.ArgumentParser(description="care-call-bot 분석기 -> 브릿지 -> DRT 연결 데모")
    parser.add_argument("utterance", help="어르신 발화")
    parser.add_argument("--analyzer",
                        default=os.getenv("CARE_CALL_BOT_PATH", str(DEFAULT_ANALYZER_DIR)),
                        help="케어콜 분석기 폴더 (기본값은 이 폴더 안의 care_call_bot)")
    parser.add_argument("--user", default="elder_demo_01")
    parser.add_argument("--offline", action="store_true", help="가짜 DRT 서버 사용")
    args = parser.parse_args()

    analyzer = load_analyzer(args.analyzer)
    result = analyzer.analyze_conversation(args.utterance)

    print("\n--- 분석 결과 ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    handoff = DrtHandoff(FakeDrtService() if args.offline else DrtServiceClient())
    outcome = handoff.handle_analysis(args.user, result)

    print("\n--- 브릿지 결과 ---")
    print(f"결정: {outcome.action} ({outcome.code})")
    if outcome.drt_request:
        print(f"DRT 요청: {json.dumps(outcome.drt_request, ensure_ascii=False)}")
    print(f"다솜이: {outcome.text}")


if __name__ == "__main__":
    main()
