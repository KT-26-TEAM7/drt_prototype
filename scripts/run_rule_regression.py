"""제공된 54개 발화 케이스를 규칙 모드로 실행해 JSON/CSV 보고서를 만든다."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.config import Settings
from carecall_drt.schemas import SessionState

INPUT = ROOT / "data" / "test_utterances.json"
OUTPUT_JSON = ROOT / "reports" / "rule_regression_results.json"
OUTPUT_CSV = ROOT / "reports" / "rule_regression_results.csv"


def main() -> None:
    cases = json.loads(INPUT.read_text(encoding="utf-8"))
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    rows = []
    for case in cases:
        result = analyzer.analyze_turn(case["utterance"], SessionState(), allow_internal_gemini=False)
        passed = (
            result.dialogue_stage == case["expected_stage"]
            and result.destination_category == case["expected_category"]
        )
        rows.append(
            {
                "id": case["id"],
                "utterance": case["utterance"],
                "expected_stage": case["expected_stage"],
                "actual_stage": result.dialogue_stage,
                "expected_category": case["expected_category"],
                "actual_category": result.destination_category,
                "target_slot": result.target_slot,
                "should_call_gemini": result.should_call_gemini,
                "rule_latency_ms": result.rule_latency_ms,
                "passed": passed,
            }
        )

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    passed = sum(row["passed"] for row in rows)
    print(f"규칙 회귀 테스트: {passed}/{len(rows)} 통과")
    print(OUTPUT_JSON)
    print(OUTPUT_CSV)
    raise SystemExit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
