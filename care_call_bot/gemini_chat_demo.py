"""메인 서버에 붙어 실제로 통화하는 케어콜 클라이언트(음성 입출력 포함).

대화 상태 관리·의도 분석·DRT 판단은 전부 메인 서버(`main_server/app.py`)가 맡는다.
이 스크립트는 어르신 발화(마이크 또는 키보드)를 받아 메인 서버의 `/call/utterance`에
넘기고, 돌아온 응답을 화면에 찍고 TTS로 읽어 주는 **입출력 껍데기** 역할만 한다
(`scripts/call_demo.py`와 같은 방식이지만, 여기는 동의 절차와 실제 음성 입출력이 있다).

실행 전:
    py scripts\\run_stack.py 로 배차 서버·drt_service·메인 서버를 먼저 띄워두세요.

실행:
    python gemini_chat_demo.py                     # 키보드 입력
    python gemini_chat_demo.py --voice              # 마이크로 말하기 (STT: faster-whisper)
    python gemini_chat_demo.py --voice --stt-model base   # 더 가벼운 STT 모델
    python gemini_chat_demo.py --no-tts              # 음성 출력(TTS) 끄기
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

import consent
from voice_io import find_korean_voice, listen, load_stt, speak

DEFAULT_SERVER = "http://127.0.0.1:8002"

SPEAKER_LABEL = {"dasom": "다솜이", "drt": "다솜이(안내)", "system": "시스템"}


# ---------- 메인 서버 클라이언트 ----------

def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"요청 실패({error.code}): {body[:200]}")
    except urllib.error.URLError as error:
        raise SystemExit(
            f"메인 서버에 붙지 못했습니다: {url}\n  {error.reason}\n"
            "  py scripts/run_stack.py 로 먼저 띄우세요."
        )


def say_and_print(text: str, voice: str | None, who: str = "다솜이") -> None:
    if not text:
        return
    print(f"{who}: {text}")
    speak(text, voice)


def main() -> None:
    parser = argparse.ArgumentParser(description="메인 서버에 붙는 케어콜 통화 데모(음성 입출력 포함)")
    parser.add_argument("--server", default=DEFAULT_SERVER, help=f"메인 서버 주소 (기본 {DEFAULT_SERVER})")
    parser.add_argument("--user", default="elder_demo_01", help="어르신 프로필 ID")
    parser.add_argument("--voice", action="store_true", help="마이크 음성 입력 사용")
    parser.add_argument("--stt-model", default="small",
                        help="faster-whisper 모델 크기 (tiny/base/small/medium, 기본 small)")
    parser.add_argument("--no-tts", action="store_true", help="음성 출력(TTS) 끄기")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)

    stt = load_stt(args.stt_model) if args.voice else None

    tts_voice = None if args.no_tts else find_korean_voice()
    if not args.no_tts and tts_voice is None:
        print("(한국어 TTS 음성을 찾지 못해 음성 출력 없이 진행합니다.)")

    ask_fn = (lambda: listen(stt)) if stt is not None else (lambda: input().strip())
    agreed = consent.get_consent(
        ask_fn=ask_fn,
        speak_fn=lambda text: speak(text, tts_voice),
        channel="main-server-voice" if stt is not None else "main-server",
    )
    if not agreed:
        say_and_print(consent.DECLINE_FAREWELL, tts_voice)
        return

    root = json.loads(urllib.request.urlopen(f"{args.server}/", timeout=10).read())
    print(f"(메인 서버: 분석기={root.get('analyzer')} / 대화={root.get('conversation')})")

    started = post(f"{args.server}/call/start", {"user_id": args.user})
    session_id = started["session_id"]
    say_and_print(started["reply"], tts_voice)

    call_ended = False
    while True:
        try:
            if stt is not None:
                user_input = listen(stt)
                if not user_input:
                    print("(잘 못 들었어요. 다시 한번 말씀해 주세요.)")
                    continue
                print(f"어르신: {user_input}")
            else:
                user_input = input("어르신: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n대화를 마칩니다.")
            break

        if not user_input:
            continue
        if user_input in ("종료", "끝", "quit", "exit") or (stt is not None and "종료" in user_input):
            break

        reply = post(f"{args.server}/call/utterance",
                     {"session_id": session_id, "text": user_input})
        who = SPEAKER_LABEL.get(reply.get("speaker", ""), "다솜이")
        say_and_print(reply["reply"], tts_voice, who)
        if reply.get("tracking_url"):
            print(f"  조회 링크: {reply['tracking_url']}")
        if reply.get("sms_sent"):
            print(f"  문자 발송: {','.join(reply['sms_sent'])}")

        if reply.get("call_ended"):
            call_ended = True
            break

    ended = post(f"{args.server}/call/end", {"session_id": session_id, "text": "종료"})
    if not call_ended:
        say_and_print(ended.get("reply", ""), tts_voice)
    print("(통화를 마칩니다.)")


if __name__ == "__main__":
    main()
