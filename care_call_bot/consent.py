"""통화 시작 전 개인정보 처리 동의를 받는 공용 모듈.

인영님이 정리한 회의록(개인정보 보호 관련) 중 "사전 고지 및 동의" 항목(개인정보보호법
제15·17·23조 근거) 가운데, 이 파트(케어콜 대화)가 실제로 처리하는 항목만 추려서
통화 시작 전에 한 번에 간략히 안내하고 동의를 받는다.

이 파트에서 다루는 항목:
- 통화 음성·STT 변환 결과 수집·이용 (대화 분석 목적)
- STT·LLM 분석 (로컬 모델 또는 Gemini 등 외부 LLM API로 전송될 수 있음)
- 건강 관련 발화(민감정보) 처리 — 어르신이 몸 상태를 말씀하시면 그 내용도 위 목적으로 처리됨

위치정보·보호자 제공·차량 배차 관련 동의는 DRT 파트 담당이라 여기서 다루지 않는다.

chat_demo.py, gemini_chat_demo.py에서 공통으로 사용한다.
"""

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

LOG_PATH = Path(__file__).parent / "consent_log.jsonl"

# 음성으로 읽혔을 때도 자연스럽도록 한두 문장씩 짧게 구성한다 (system_prompt.txt와 같은 톤 규칙).
CONSENT_NOTICE = (
    "통화를 시작하기 전에 잠깐 안내드릴게요. "
    "이 통화 내용은 글로 바뀌어서, 어르신을 더 잘 도와드리기 위해 인공지능이 함께 확인해요. "
    "몸이 편찮으시다는 말씀도 같은 목적으로만 쓰이고, 안전하게 관리되다가 다 쓰고 나면 지워져요."
)
CONSENT_QUESTION = "이렇게 진행해도 괜찮으실까요? 네 또는 아니오로 말씀해 주세요."

DECLINE_FAREWELL = "네, 알겠습니다. 다음에 다시 연락드릴게요. 건강히 지내세요."

AGREE_PATTERNS = ["네", "예", "응", "좋아", "동의", "괜찮", "그래", "오케이", "okay", "ok", "yes"]
DECLINE_PATTERNS = ["아니", "싫", "안 할래", "안할래", "동의 안", "거부", "no"]


def classify_response(text: str) -> Optional[bool]:
    """동의/거부/판단불가(None)로 분류한다."""
    compact = text.strip().lower()
    if any(p in compact for p in DECLINE_PATTERNS):
        return False
    if any(p in compact for p in AGREE_PATTERNS):
        return True
    return None


def log_consent(agreed: bool, channel: str) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "channel": channel,
        "agreed": agreed,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        import json

        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_consent(
    ask_fn: Callable[[], str],
    speak_fn: Callable[[str], None],
    channel: str,
    print_fn: Callable[[str], None] = print,
) -> bool:
    """동의 안내 후 사용자 응답을 받아 동의 여부(bool)를 반환하고 로그를 남긴다.

    응답이 애매하면 한 번 더 물어보고, 그래도 애매하면 안전하게 '거부'로 처리한다.
    """
    full_notice = f"{CONSENT_NOTICE} {CONSENT_QUESTION}"
    print_fn(f"다솜이: {full_notice}")
    speak_fn(full_notice)

    for attempt in range(2):
        response = ask_fn()
        print_fn(f"어르신: {response}")
        result = classify_response(response)
        if result is not None:
            log_consent(result, channel)
            return result
        if attempt == 0:
            retry_msg = "네, 하시겠다는 건지 아니라는 건지만 말씀해 주시면 돼요."
            print_fn(f"다솜이: {retry_msg}")
            speak_fn(retry_msg)

    log_consent(False, channel)
    return False
