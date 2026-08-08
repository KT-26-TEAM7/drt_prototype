"""다솜이의 대화 응답(안부 대화)을 만든다.

## 한 턴에 한 마디만 말한다

전에는 다솜이(LLM)가 자기 답변을 하고, 그 뒤에 브릿지가 DRT 안내를 따로 붙였다.
그러면 한 턴에 두 문단이 연달아 나가서 `prompts/system_prompt.txt`의
"한 번에 한두 문장, 질문은 하나만" 규칙과 정면으로 부딪친다.

메인 서버는 **누가 말할지 매 턴 하나만 고른다**(`app.py` 참고).

    DRT 쪽에서 할 말이 있으면  -> 그 말만 한다 (예약 확인, 되물음, 배차 완료)
    할 말이 없으면            -> 다솜이가 안부 대화를 잇는다 (이 파일)

## 키가 없을 때

`care_call_bot/.env`에 `GEMINI_KEY`가 없으면 LLM을 부르지 않고, 대화를 잇는 짧은
맞장구만 돌려준다. 통화가 끊기지 않게 하려는 것이지 품질을 대신하지는 못한다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
CARE_CALL_DIR = PROJECT_DIR / "care_call_bot"
SYSTEM_PROMPT_PATH = CARE_CALL_DIR / "prompts" / "system_prompt.txt"

GREETING = "안녕하세요, 어르신. 말벗 다솜이예요. 요즘 잘 지내고 계세요?"
FAREWELL = "오늘 이야기 나눠서 즐거웠어요. 또 전화드릴게요. 건강히 지내세요."
END_CALL_MARKER = "[통화종료]"

DEFAULT_MODEL = "gemini-flash-latest"

# LLM을 못 쓸 때 대화를 잇는 최소 맞장구. 순서대로 돌려 쓴다.
_FALLBACK_REPLIES = (
    "그러셨군요. 요즘 식사는 잘 챙겨 드세요?",
    "네, 말씀 잘 들었어요. 잠은 편히 주무시고요?",
    "그러셨구나. 요즘 몸은 좀 어떠세요?",
    "네, 그러셨군요. 기분은 좀 어떠세요?",
    "말씀해 주셔서 고마워요. 요즘 어디 다녀오신 데는 있으세요?",
)


def load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "너는 어르신의 다정한 말벗 다솜이다. 존댓말로 한두 문장만 말한다."


def strip_end_marker(reply: str) -> tuple[str, bool]:
    """모델이 붙인 통화 종료 표식을 떼어내고 종료 여부를 함께 돌려준다."""
    if END_CALL_MARKER in reply:
        return reply.replace(END_CALL_MARKER, "").strip(), True
    return reply.strip(), False


class CareCallTalker:
    """세션마다 대화 이력을 들고 다솜이 응답을 만든다."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._chats: dict[str, Any] = {}
        self._fallback_index: dict[str, int] = {}
        self._client: Any = None
        self._client_ready = False
        self.load_error: str = ""

    @property
    def uses_llm(self) -> bool:
        return self._ensure_client() is not None

    def _ensure_client(self) -> Any:
        if self._client_ready:
            return self._client
        self._client_ready = True
        try:
            from dotenv import load_dotenv
            from google import genai
        except ModuleNotFoundError as exc:
            self.load_error = f"{exc.name} 없음 — 맞장구로 대신합니다."
            return None

        # 분석기와 같은 .env를 읽는다(care_call_bot/.env).
        load_dotenv(CARE_CALL_DIR / ".env")
        api_key = os.getenv("GEMINI_KEY", "").strip()
        if not api_key:
            self.load_error = "GEMINI_KEY가 없어 맞장구로 대신합니다."
            return None
        try:
            self._client = genai.Client(api_key=api_key)
        except Exception as exc:  # 키 형식 오류 등
            self.load_error = f"Gemini 준비 실패: {type(exc).__name__}"
            self._client = None
        return self._client

    def reply(self, session_id: str, utterance: str) -> tuple[str, bool]:
        """어르신 말씀에 대한 다솜이 응답과 통화 종료 여부."""
        client = self._ensure_client()
        if client is None:
            return self._fallback_reply(session_id), False

        try:
            from google.genai import types

            chat = self._chats.get(session_id)
            if chat is None:
                chat = client.chats.create(
                    model=self.model,
                    config=types.GenerateContentConfig(system_instruction=load_system_prompt()),
                    history=[types.Content(role="model", parts=[types.Part(text=GREETING)])],
                )
                self._chats[session_id] = chat
            response = chat.send_message(utterance)
            return strip_end_marker(response.text or "")
        except Exception as exc:
            # 통화 중 LLM이 흔들려도 끊기지 않게 한다.
            self.load_error = f"Gemini 호출 실패: {type(exc).__name__}"
            return self._fallback_reply(session_id), False

    def _fallback_reply(self, session_id: str) -> str:
        index = self._fallback_index.get(session_id, 0)
        self._fallback_index[session_id] = index + 1
        return _FALLBACK_REPLIES[index % len(_FALLBACK_REPLIES)]

    def end(self, session_id: str) -> None:
        self._chats.pop(session_id, None)
        self._fallback_index.pop(session_id, None)
