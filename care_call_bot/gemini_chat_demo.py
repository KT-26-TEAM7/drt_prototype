"""Gemini API 기반 어르신 안부 케어콜 챗봇 데모.

`prompts/system_prompt.txt`의 페르소나를 그대로 사용해 Gemini API를 호출한다.
매 턴마다 응답 소요 시간을 함께 출력한다.

실행 전:
    .env 파일에 GEMINI_KEY="발급받은 API 키" 를 넣어두세요.

실행:
    python gemini_chat_demo.py                       # 기본 모델(gemini-flash-latest)
    python gemini_chat_demo.py --model gemini-2.5-flash-lite
    python gemini_chat_demo.py --no-tts               # 음성 출력(TTS) 끄기
"""

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

import consent
import drt_analyzer

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.txt"

# 케어콜은 봇이 먼저 말을 건다. 첫인사는 고정 멘트로 시작.
GREETING = "안녕하세요, 어르신. 말벗 다솜이예요. 요즘 잘 지내고 계세요?"

# 모델명은 Gemini 쪽 라인업이 자주 바뀌므로, 특정 버전에 고정하지 않고
# "가장 빠른 최신 flash 모델"을 가리키는 별칭을 기본값으로 사용한다.
DEFAULT_MODEL = "gemini-flash-latest"

END_CALL_MARKER = "[통화종료]"


def load_client() -> genai.Client:
    load_dotenv()
    api_key = os.getenv("GEMINI_KEY")
    if not api_key:
        raise SystemExit(
            "GEMINI_KEY를 찾지 못했습니다. 프로젝트 루트 .env 파일에 "
            'GEMINI_KEY="발급받은 API 키" 를 넣어주세요.'
        )
    return genai.Client(api_key=api_key)


def check_end_call(reply: str) -> tuple[str, bool]:
    if END_CALL_MARKER in reply:
        return reply.replace(END_CALL_MARKER, "").strip(), True
    return reply, False


def find_korean_voice() -> str | None:
    import shutil
    import subprocess

    if shutil.which("say") is None:
        return None
    voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    korean = [line.split()[0] for line in voices.splitlines() if "ko_KR" in line]
    if not korean:
        return None
    return "Yuna" if "Yuna" in korean else korean[0]


def speak(text: str, voice: str | None):
    if voice is None or not text:
        return
    import subprocess

    subprocess.run(["say", "-v", voice, text])


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini API 기반 케어콜 챗봇 데모")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini 모델명 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--no-tts", action="store_true", help="음성 출력(TTS) 끄기")
    args = parser.parse_args()

    client = load_client()
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    tts_voice = None if args.no_tts else find_korean_voice()
    if not args.no_tts and tts_voice is None:
        print("(한국어 TTS 음성을 찾지 못해 음성 출력 없이 진행합니다.)")

    agreed = consent.get_consent(
        ask_fn=lambda: input().strip(),
        speak_fn=lambda text: speak(text, tts_voice),
        channel="gemini-api",
    )
    if not agreed:
        print(f"다솜이: {consent.DECLINE_FAREWELL}")
        speak(consent.DECLINE_FAREWELL, tts_voice)
        return

    chat = client.chats.create(
        model=args.model,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
        history=[
            types.Content(role="model", parts=[types.Part(text=GREETING)]),
        ],
    )

    print(f"(모델: {args.model})")
    print()
    print(f"다솜이(Gemini): {GREETING}")
    speak(GREETING, tts_voice)

    drt_transcript: list[str] = []

    while True:
        try:
            user_input = input("어르신: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n대화를 마칩니다.")
            break

        if not user_input:
            continue
        if user_input in ("종료", "끝", "quit", "exit"):
            farewell = "오늘 이야기 나눠서 즐거웠어요. 또 전화드릴게요. 건강히 지내세요."
            print(f"다솜이(Gemini): {farewell}")
            speak(farewell, tts_voice)
            break

        start = time.time()
        response = chat.send_message(user_input)
        elapsed = time.time() - start

        reply, end_call = check_end_call(response.text or "")
        print(f"다솜이(Gemini): {reply}  [{elapsed:.2f}초]")
        speak(reply, tts_voice)

        drt_transcript.append(f"어르신: {user_input}")
        drt_result = drt_analyzer.analyze_conversation("\n".join(drt_transcript))
        print(drt_analyzer.format_drt_summary(drt_result))

        if end_call:
            print("(통화를 마칩니다.)")
            break


if __name__ == "__main__":
    main()
