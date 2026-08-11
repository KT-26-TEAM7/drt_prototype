from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.config import Settings
from carecall_drt.schemas import SessionState

CASES = json.loads((Path(__file__).parents[1] / "data" / "test_utterances.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_source_utterance_matrix(case: dict) -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    result = analyzer.analyze_turn(case["utterance"], SessionState(), allow_internal_gemini=False)
    assert result.dialogue_stage == case["expected_stage"]
    assert result.destination_category == case["expected_category"]


def test_emergency_never_requests_gemini() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="candidate"))
    result = analyzer.analyze_turn("숨이 잘 안 쉬어지고 가슴이 아파", SessionState())
    assert result.emergency_risk is True
    assert result.should_call_gemini is False
    assert result.dialogue_stage == "emergency"


def test_refusal_never_requests_gemini() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="candidate"))
    result = analyzer.analyze_turn("약국은 가야 하지만 택시 타고 갈게. 차는 안 불러도 돼", SessionState())
    assert result.should_call_gemini is False
    assert result.dialogue_stage == "not_needed"


def test_casual_turn_has_no_drt_question() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    result = analyzer.analyze_turn("어제 잠을 잘 못 자서 피곤하네", SessionState())
    assert result.dialogue_stage == "need_detection"
    assert result.target_slot is None
    assert result.next_question == ""
    assert result.missing_slots == []


def test_rule_matrix_is_fast() -> None:
    analyzer = DRTAnalyzer(Settings(gemini_policy="off"))
    started = time.perf_counter()
    for case in CASES:
        analyzer.analyze_turn(case["utterance"], SessionState(), allow_internal_gemini=False)
    assert time.perf_counter() - started < 2.0
