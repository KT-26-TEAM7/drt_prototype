"""마이크 음성 입력(STT)·스피커 음성 출력(TTS) 공용 유틸리티.

`gemini_chat_demo.py`, `openai_chat_demo.py`가 공통으로 쓴다. STT는
faster-whisper(로컬 Whisper, CTranslate2 기반이라 torch 불필요), TTS는 macOS
내장 `say` 명령을 쓴다 — Windows에서는 TTS 없이 텍스트로만 동작한다.
"""

from __future__ import annotations

# ---------- TTS (음성 출력) ----------


def find_korean_voice() -> str | None:
    """macOS `say`의 한국어 음성 이름을 찾는다. 없으면 None."""
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


# ---------- STT (음성 입력) ----------

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.01   # 이보다 작은 RMS는 침묵으로 간주 (환경에 따라 조절)
SILENCE_DURATION = 1.5     # 말이 시작된 뒤 이만큼 조용하면 녹음 종료 (초)
MAX_RECORD_SECONDS = 30    # 최대 녹음 길이 (초)
WAIT_FOR_SPEECH_SECONDS = 10  # 말이 시작되길 기다리는 최대 시간 (초)


def load_stt(model_size: str):
    from faster_whisper import WhisperModel

    print(f"음성 인식 모델 로딩 중... (faster-whisper {model_size})")
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def record_audio():
    """마이크로 녹음. 말이 시작된 뒤 일정 시간 조용해지면 자동 종료.

    말이 감지되지 않으면 None을 반환한다.
    """
    import numpy as np
    import sounddevice as sd

    block_seconds = 0.1
    block_size = int(SAMPLE_RATE * block_seconds)
    chunks = []
    speech_started = False
    silent_blocks = 0
    waited_blocks = 0

    print("(말씀하세요...)", flush=True)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=block_size) as stream:
        while True:
            block, _ = stream.read(block_size)
            block = block[:, 0]
            rms = float(np.sqrt(np.mean(block ** 2)))

            if not speech_started:
                waited_blocks += 1
                if rms >= SILENCE_THRESHOLD:
                    speech_started = True
                    chunks.append(block)
                elif waited_blocks * block_seconds >= WAIT_FOR_SPEECH_SECONDS:
                    return None
                continue

            chunks.append(block)
            silent_blocks = silent_blocks + 1 if rms < SILENCE_THRESHOLD else 0

            if silent_blocks * block_seconds >= SILENCE_DURATION:
                break
            if len(chunks) * block_seconds >= MAX_RECORD_SECONDS:
                break

    return np.concatenate(chunks)


def listen(stt) -> str:
    """녹음 후 텍스트로 변환. 인식 실패 시 빈 문자열 반환."""
    audio = record_audio()
    if audio is None:
        return ""
    segments, _ = stt.transcribe(audio, language="ko", vad_filter=True)
    return "".join(segment.text for segment in segments).strip()
