from __future__ import annotations

from carecall_drt.analyzer import DRTAnalyzer
from carecall_drt.config import Settings
from carecall_drt.responses import compose_reply
from carecall_drt.schemas import SessionState


def _analysis(text: str):
    return DRTAnalyzer(Settings(gemini_policy="off")).analyze_turn(
        text, SessionState(), allow_internal_gemini=False
    )


def test_drt_reply_uses_exactly_one_rule_question() -> None:
    analysis = _analysis("가까운 정형외과에 가고 싶어")
    reply = compose_reply("무릎이 아프셔서 힘드시겠어요. 어느 병원에 가실까요? 언제 가실까요?", analysis)
    assert reply.count("?") == 1
    assert reply.endswith(analysis.next_question)


def test_emergency_reply_is_fixed_and_not_llm_led() -> None:
    analysis = _analysis("숨이 잘 안 쉬어지고 가슴이 아파")
    reply = compose_reply("괜찮으실 거예요.", analysis)
    assert "119" in reply
    assert "괜찮으실" not in reply


def test_casual_reply_preserves_one_question() -> None:
    analysis = _analysis("오늘 밥은 먹었어")
    reply = compose_reply("잘 챙겨 드셨군요. 오늘 기분은 어떠세요? 잠은 잘 주무셨어요?", analysis)
    assert reply.count("?") == 1
