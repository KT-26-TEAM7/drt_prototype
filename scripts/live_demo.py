"""옛 care-call-bot 분석기 출력 형식으로 브릿지 파이프라인을 끝까지 흘려 보는 데모.

**2026-08-11 이후**: 이 폴더 안의 `care_call_bot/drt_analyzer.py`는 `carecall_drt`로
대체되어 삭제되었다(docs/04_carecall_drt_이식.md). 이 스크립트는 브릿지의
`bridge/contract.py`가 정의하는 **옛 분석기 출력 계약**(`search_mode`/`search_keywords`
등)을 그대로 데모하는 도구라, carecall_drt(다른 필드 체계)로는 대체할 수 없다. 그래서
여전히 외부의 원본 care-call-bot 체크아웃(또는 같은 출력 형식을 내는 분석기)을
`--analyzer` 경로로 받아서만 동작한다 — 로컬 기본 경로는 없다.

    py scripts/live_demo.py "어르신: 가까운 치과에 가려는데 차 좀 불러줘." ^
        --analyzer "C:\\Users\\hyung\\Downloads\\care-call-bot-main\\care-call-bot-main" --offline

`--analyzer`를 생략하면 환경변수 CARE_CALL_BOT_PATH를 쓴다. **외부 분석기 없이 같은
브릿지 파이프라인을 보고 싶으면** 미리 만들어 둔 분석 결과 JSON을 쓰는
`scripts/run_handoff.py samples\\*.json --offline`을 대신 쓰면 된다.
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


def load_analyzer(analyzer_dir: str):
    path = Path(analyzer_dir).expanduser()
    if not (path / "drt_analyzer.py").exists():
        raise SystemExit(
            f"drt_analyzer.py를 찾지 못했습니다: {path}\n"
            "이 폴더 안의 care_call_bot/drt_analyzer.py는 carecall_drt로 대체되어 "
            "삭제되었습니다(docs/04_carecall_drt_이식.md). --analyzer로 외부 "
            "care-call-bot 체크아웃 경로를 주거나, 분석기 없이 같은 파이프라인을 보려면 "
            "scripts/run_handoff.py samples\\*.json --offline 을 쓰세요."
        )
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
                        default=os.getenv("CARE_CALL_BOT_PATH", ""),
                        help="케어콜 분석기 폴더(외부 care-call-bot 체크아웃). "
                             "생략 시 CARE_CALL_BOT_PATH 환경변수를 쓴다")
    parser.add_argument("--user", default="elder_demo_01")
    parser.add_argument("--offline", action="store_true", help="가짜 DRT 서버 사용")
    args = parser.parse_args()

    if not args.analyzer:
        raise SystemExit(
            "--analyzer 경로가 없습니다(또는 CARE_CALL_BOT_PATH 환경변수를 설정하세요). "
            "분석기 없이 같은 파이프라인을 보려면 "
            "scripts/run_handoff.py samples\\*.json --offline 을 쓰세요."
        )
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
