"""선택적 STT/TTS 유틸리티.

음성 기능을 사용하지 않으면 관련 패키지를 import하지 않는다.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 0.01
SILENCE_DURATION = 1.5
MAX_RECORD_SECONDS = 30
WAIT_FOR_SPEECH_SECONDS = 10


def load_stt(model_size: str = "small") -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install -r requirements-voice.txt를 실행하세요.") from exc
    print(f"음성 인식 모델 로딩 중... (faster-whisper {model_size})")
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def record_audio():
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("numpy와 sounddevice가 필요합니다.") from exc

    block_seconds = 0.1
    block_size = int(SAMPLE_RATE * block_seconds)
    chunks = []
    speech_started = False
    silent_blocks = 0
    waited_blocks = 0

    print("(말씀하세요...)", flush=True)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=block_size) as stream:
        while True:
            block, _ = stream.read(block_size)
            block = block[:, 0]
            rms = float(np.sqrt(np.mean(block**2)))
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


def listen(stt: Any) -> str:
    audio = record_audio()
    if audio is None:
        return ""
    segments, _ = stt.transcribe(audio, language="ko", vad_filter=True)
    return "".join(segment.text for segment in segments).strip()


def detect_tts() -> tuple[str, str] | None:
    system = platform.system()
    if system == "Darwin" and shutil.which("say"):
        return "mac", "Yuna"
    if system == "Windows" and shutil.which("powershell"):
        return "windows", ""
    if shutil.which("espeak"):
        return "espeak", "ko"
    return None


def speak(text: str, engine: tuple[str, str] | None) -> None:
    if not text or engine is None:
        return
    kind, voice = engine
    if kind == "mac":
        subprocess.run(["say", "-v", voice, text], check=False)
    elif kind == "windows":
        escaped = text.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{escaped}')"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False)
    else:
        subprocess.run(["espeak", "-v", voice, text], check=False)
