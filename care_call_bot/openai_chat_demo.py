"""OpenAI Realtime API 기반 어르신 안부 케어콜 챗봇 데모.

gemini_chat_demo.py(Gemini API)와 같은 페르소나·시스템 프롬프트를 사용하되,
OpenAI Realtime API로 음성을 직접 주고받는다.
STT/TTS를 따로 두지 않고, 마이크 오디오를 실시간으로 서버에 보내고
서버가 만든 오디오를 그대로 스피커로 재생한다 (speech-to-speech).

실행 전:
    .env 파일에 OPENAI_API_KEY="발급받은 API 키" 를 넣어두세요.

실행:
    python openai_chat_demo.py                       # 기본 모델(gpt-realtime)
    python openai_chat_demo.py --model gpt-realtime
    python openai_chat_demo.py --openai-voice marin   # 응답 음성 지정
"""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets
from dotenv import load_dotenv

import consent
from voice_io import find_korean_voice, listen, load_stt, speak

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.txt"

DEFAULT_MODEL = "gpt-realtime"
DEFAULT_VOICE = "marin"

END_CALL_MARKER = "[통화종료]"
END_CALL_WORDS = ("종료", "끝", "quit", "exit")

REALTIME_URL = "wss://api.openai.com/v1/realtime"

# Realtime API가 오디오로 주고받는 고정 포맷.
SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK_MS = 100
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000


def load_api_key() -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY를 찾지 못했습니다. 프로젝트 루트 .env 파일에 "
            'OPENAI_API_KEY="발급받은 API 키" 를 넣어주세요.'
        )
    return api_key


def check_end_call(reply: str) -> tuple[str, bool]:
    if END_CALL_MARKER in reply:
        return reply.replace(END_CALL_MARKER, "").strip(), True
    return reply, False


class RealtimeCall:
    """마이크 입력을 서버로 스트리밍하고, 서버 오디오를 스피커로 재생하는 세션."""

    def __init__(self, ws, model: str):
        self.ws = ws
        self.model = model
        self.out_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16"
        )
        self.out_stream.start()
        self.assistant_transcript = ""
        self.end_call = False
        self.turn_done = asyncio.Event()

    async def configure(self, system_prompt: str, voice: str):
        await self.ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "output_modalities": ["audio"],
                "instructions": system_prompt,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                        "turn_detection": {
                            "type": "server_vad",
                            # 조용한 실내 잡음까지 "말했다"고 판단해서 STT가
                            # 뉴스 자막 같은 문구를 지어내는(환각) 걸 줄이기 위해
                            # 기본값보다 임계값/최소 침묵 시간을 올린다.
                            "threshold": 0.6,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 700,
                        },
                        "transcription": {"model": "whisper-1"},
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                        "voice": voice,
                    },
                },
            },
        }))

    async def start_conversation(self):
        """고정 인사말 없이, 시스템 프롬프트 지시대로 모델이 먼저 말을 걸게 한다."""
        await self.ws.send(json.dumps({"type": "response.create"}))

    async def send_mic_audio(self):
        """마이크를 계속 읽어 append 이벤트로 보낸다. 턴 종료는 서버 VAD가 판단."""
        loop = asyncio.get_event_loop()
        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
            blocksize=CHUNK_SAMPLES,
        ) as stream:
            while True:
                block, _ = await loop.run_in_executor(None, stream.read, CHUNK_SAMPLES)
                audio_b64 = base64.b64encode(block.tobytes()).decode("ascii")
                await self.ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_b64,
                }))

    async def receive_events(self):
        """서버 이벤트를 처리: 오디오는 재생, 텍스트는 콘솔 출력 + 종료 감지."""
        user_transcript = ""
        async for raw in self.ws:
            event = json.loads(raw)
            etype = event.get("type")

            if etype in ("response.output_audio.delta", "response.audio.delta"):
                chunk = base64.b64decode(event["delta"])
                self.out_stream.write(np.frombuffer(chunk, dtype=np.int16))
            elif etype in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
                self.assistant_transcript += event.get("delta", "")
            elif etype == "conversation.item.input_audio_transcription.completed":
                user_transcript = event.get("transcript", "").strip()
                if user_transcript:
                    print(f"어르신: {user_transcript}")
            elif etype == "response.done":
                reply, end_call = check_end_call(self.assistant_transcript)
                print(f"OpenAI: {reply}")
                self.assistant_transcript = ""
                user_transcript = ""
                if end_call or any(w in reply for w in END_CALL_WORDS if w == "종료"):
                    self.end_call = True
                self.turn_done.set()
            elif etype == "error":
                print(f"(오류: {event.get('error')})")


async def run_call(api_key: str, model: str, voice: str, system_prompt: str):
    url = f"{REALTIME_URL}?model={model}"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        call = RealtimeCall(ws, model)
        await call.configure(system_prompt, voice)

        print(f"(모델: {model}, 음성: {voice})")
        print()
        await call.start_conversation()

        mic_task = asyncio.create_task(call.send_mic_audio())
        recv_task = asyncio.create_task(call.receive_events())

        try:
            while not call.end_call:
                await asyncio.sleep(0.2)
            print("(통화를 마칩니다.)")
        finally:
            mic_task.cancel()
            recv_task.cancel()
            call.out_stream.stop()
            call.out_stream.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI Realtime API 기반 케어콜 챗봇 데모")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Realtime 모델명 (기본 {DEFAULT_MODEL})")
    parser.add_argument("--openai-voice", default=DEFAULT_VOICE, help=f"응답 음성 (기본 {DEFAULT_VOICE})")
    parser.add_argument("--stt-model", default="small",
                        help="동의 단계에서 쓰는 faster-whisper 모델 크기 (기본 small)")
    args = parser.parse_args()

    api_key = load_api_key()
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    # 동의 단계는 다른 데모와 동일하게 별도 STT/TTS로 처리하고,
    # 동의가 끝난 뒤에만 Realtime 오디오 세션을 연다.
    stt = load_stt(args.stt_model)
    tts_voice = find_korean_voice()
    if tts_voice is None:
        print("(한국어 TTS 음성을 찾지 못해 동의 안내를 음성 없이 진행합니다.)")

    agreed = consent.get_consent(
        ask_fn=lambda: listen(stt),
        speak_fn=lambda text: speak(text, tts_voice),
        channel="openai-realtime",
    )
    if not agreed:
        print(f"OpenAI: {consent.DECLINE_FAREWELL}")
        speak(consent.DECLINE_FAREWELL, tts_voice)
        return

    try:
        asyncio.run(run_call(api_key, args.model, args.openai_voice, system_prompt))
    except KeyboardInterrupt:
        print("\n대화를 마칩니다.")


if __name__ == "__main__":
    main()
