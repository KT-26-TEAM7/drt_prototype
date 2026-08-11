from __future__ import annotations

from carecall_drt.analyzer import DRTAnalyzer, make_rule_semantic, merge_semantic
from carecall_drt.config import Settings
from carecall_drt.schemas import SessionState


class FakeEnricher:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def analyze(self, conversation: str):
        self.calls += 1
        return self.payload, 1.2


def test_gemini_cannot_invent_specific_place() -> None:
    rule = make_rule_semantic("가까운 약국에 가고 싶어")
    merged = merge_semantic(
        rule,
        {
            "visit_intent": True,
            "destination_category": "pharmacy",
            "destination_candidates": ["중앙약국"],
            "specific_place": "중앙약국",
            "place_preference": "exact",
            "extracted_keywords": ["약국"],
        },
        "가까운 약국에 가고 싶어",
    )
    assert merged.specific_place == ""
    assert merged.place_preference == "nearby"


def test_gemini_specific_place_allowed_only_when_in_text() -> None:
    rule = make_rule_semantic("중앙약국으로 가고 싶어")
    assert rule.specific_place == "중앙약국"
    merged = merge_semantic(rule, {"specific_place": "중앙약국"}, "중앙약국으로 가고 싶어")
    assert merged.specific_place == "중앙약국"


def test_rule_safety_values_win_over_llm() -> None:
    rule = make_rule_semantic("약국은 가야 하지만 택시 타고 갈게. 차는 안 불러도 돼")
    merged = merge_semantic(
        rule,
        {
            "visit_intent": True,
            "destination_category": "shopping_mart",
            "specific_place": "가짜마트",
            "place_preference": "exact",
        },
        "약국은 가야 하지만 택시 타고 갈게. 차는 안 불러도 돼",
    )
    assert merged.destination_category == "pharmacy"
    assert merged.outing_status == "refused"
    assert merged.reservation_consent == "refused"


def test_ambiguous_medical_general_calls_enricher_once() -> None:
    enricher = FakeEnricher(
        {
            "visit_intent": True,
            "destination_category": "medical_orthopedics",
            "destination_candidates": ["정형외과"],
            "specific_place": "",
            "place_preference": "nearby",
            "extracted_keywords": ["무릎"],
        }
    )
    analyzer = DRTAnalyzer(Settings(gemini_policy="ambiguous_only"), semantic_enricher=enricher)
    result = analyzer.analyze_turn("병원에 가고 싶어", SessionState())
    assert enricher.calls == 1
    assert result.gemini_used is True


def test_clear_category_skips_enricher_in_ambiguous_policy() -> None:
    enricher = FakeEnricher({})
    analyzer = DRTAnalyzer(Settings(gemini_policy="ambiguous_only"), semantic_enricher=enricher)
    result = analyzer.analyze_turn("가까운 정형외과에 가고 싶어", SessionState())
    assert enricher.calls == 0
    assert result.should_call_gemini is False
