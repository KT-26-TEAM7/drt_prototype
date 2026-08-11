"""다솜이 응답 후처리와 규칙 기반 폴백 문구."""

from __future__ import annotations

import re
from typing import Sequence

from .schemas import DRTAnalysis, JointLLMResult, SessionState

END_CALL_MARKER = "[통화종료]"
GREETING = "안녕하세요, 어르신. 말벗 다솜이예요. 요즘 잘 지내고 계세요?"


def check_end_call(reply: str) -> tuple[str, bool]:
    value = (reply or "").strip()
    return value.replace(END_CALL_MARKER, "").strip(), END_CALL_MARKER in value


def _one_question(reply: str) -> str:
    """일상 응답에서도 질문 부호가 둘 이상 나오지 않도록 방어한다."""
    text = re.sub(r"\s+", " ", (reply or "").strip())
    if text.count("?") <= 1:
        return text
    first = text.find("?")
    return text[: first + 1].strip()


def _empathy_only(reply: str) -> str:
    """DRT 고정 질문 앞에 붙일 공감 문장만 남긴다."""
    text, _ = check_end_call(reply)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    # 질문 문장은 제거하고 첫 번째 서술 문장만 사용한다.
    chunks = re.split(r"(?<=[.!?。])\s+|\n+", text)
    for chunk in chunks:
        cleaned = chunk.strip()
        if cleaned and "?" not in cleaned and "까요" not in cleaned and "세요" not in cleaned[-4:]:
            return cleaned[:120]
    # 문장 경계가 없는 경우 물음표 이후를 버린다.
    cleaned = text.split("?", 1)[0].strip()
    return cleaned[:120] if cleaned else ""


def default_empathy(analysis: DRTAnalysis) -> str:
    if analysis.emergency_risk:
        return "많이 위급해 보입니다."
    if analysis.dialogue_stage == "reservation_confirm":
        return "외출하실 일이 있으시군요."
    if analysis.dialogue_stage == "reservation_info_collection":
        return "이동 차량 예약에 필요한 내용을 차근차근 확인할게요."
    return "말씀해 주셔서 고맙습니다."


def compose_reply(generated: str, analysis: DRTAnalysis) -> str:
    """LLM 말투와 규칙 질문을 충돌 없이 합친다."""
    if analysis.emergency_risk:
        question = analysis.next_question or "지금 바로 보호자나 119에 연락해드릴까요?"
        return f"많이 위급해 보입니다. 움직이지 마시고 즉시 도움을 요청해 주세요. {question}".strip()

    if analysis.dialogue_stage == "not_needed":
        fallback = "알겠습니다, 어르신. 편히 쉬시고 필요하실 때 말씀해 주세요."
        return _one_question(generated or fallback)

    if analysis.next_question:
        empathy = _empathy_only(generated) or default_empathy(analysis)
        return f"{empathy} {analysis.next_question}".strip()

    fallback = "말씀해 주셔서 고맙습니다. 오늘은 몸은 좀 어떠세요?"
    return _one_question(generated or fallback)


class RuleCareResponder:
    """API 키와 대형 모델 없이 통합 흐름을 검증하는 폴백 응답기."""

    def respond(
        self,
        history: Sequence[dict[str, str]],
        user_text: str,
        *,
        drt_candidate: bool,
        analysis_hint: DRTAnalysis | None,
        state: SessionState,
    ) -> JointLLMResult:
        text = user_text.replace(" ", "")
        if drt_candidate:
            reply = "외출이나 이동이 필요하신 상황이군요."
        elif any(word in text for word in ("밥", "점심", "저녁", "식사")):
            reply = "식사 이야기를 들으니 다행이에요. 오늘 몸은 좀 어떠세요?"
        elif any(word in text for word in ("잠", "피곤", "졸려")):
            reply = "잠을 편히 못 주무셔서 피곤하시겠어요. 지금은 조금 쉬고 계세요?"
        elif any(word in text for word in ("아들", "딸", "가족", "손자", "손녀")):
            reply = "가족 소식을 들으셨군요. 통화하고 나니 마음은 좀 어떠셨어요?"
        elif any(word in text for word in ("춥", "덥", "날씨")):
            reply = "날씨가 불편하게 느껴지셨군요. 집 안에서는 따뜻하게 계세요?"
        else:
            reply = "그렇군요, 어르신. 오늘 기분은 좀 어떠세요?"
        return JointLLMResult(assistant_reply=reply, semantic_call_attempted=False)
