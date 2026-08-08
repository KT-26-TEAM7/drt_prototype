"""Mi:dm 2.0 기반 어르신 안부 케어콜 챗봇 데모.

실행:
    python chat_demo.py            # Mini(2B) 모델, 키보드 입력
    python chat_demo.py --base     # Base(12B) 모델 사용
    python chat_demo.py --voice    # 마이크로 말하기 (STT: faster-whisper)
    python chat_demo.py --no-tts   # 음성 출력(TTS) 끄기

- TTS는 macOS 내장 `say` 명령(한국어 음성 Yuna)을 사용한다.
- 어르신이 "이제 끊을게" 등 대화를 마치는 말을 하면 모델이 작별 인사 후
  [통화종료] 표식을 붙이고, 코드가 이를 감지해 자동 종료한다.
- 수동 종료: "종료"라고 입력(또는 말하기) 또는 Ctrl+C
"""

import argparse
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

import consent
import drt_analyzer

MINI_MODEL = "K-intelligence/Midm-2.0-Mini-Instruct"
BASE_MODEL = "K-intelligence/Midm-2.0-Base-Instruct"

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.txt"

# 케어콜은 봇이 먼저 말을 건다. 첫인사는 고정 멘트로 시작.
GREETING = "안녕하세요, 어르신. 말벗 다솜이예요. 요즘 잘 지내고 계세요?"


def load_model(model_name: str):
    print(f"모델 로딩 중... ({model_name})")
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map="auto",
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    generation_config = GenerationConfig.from_pretrained(model_name)
    return model, tokenizer, generation_config


def generate_reply(model, tokenizer, generation_config, messages) -> str:
    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)

    output = model.generate(
        input_ids=inputs["input_ids"],
        attention_mask=inputs["attention_mask"],
        generation_config=generation_config,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.eos_token_id,
        max_new_tokens=128,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
        repetition_penalty=1.05,
    )
    reply = tokenizer.decode(
        output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
    )
    return reply.strip()


# ---------- 통화 종료 ----------

# 시스템 프롬프트가 대화를 끝낼 때 답변 끝에 붙이도록 지시한 표식
END_CALL_MARKER = "[통화종료]"


def check_end_call(reply: str) -> tuple[str, bool]:
    """모델 답변에서 통화 종료 표식을 떼어내고, 종료 여부를 함께 반환."""
    if END_CALL_MARKER in reply:
        return reply.replace(END_CALL_MARKER, "").strip(), True
    return reply, False


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


def record_audio() -> np.ndarray | None:
    """마이크로 녹음. 말이 시작된 뒤 일정 시간 조용해지면 자동 종료.

    말이 감지되지 않으면 None을 반환한다.
    """
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


def main():
    parser = argparse.ArgumentParser(description="어르신 안부 케어콜 챗봇 데모")
    parser.add_argument("--base", action="store_true", help="Base(12B) 모델 사용")
    parser.add_argument("--voice", action="store_true", help="마이크 음성 입력 사용")
    parser.add_argument("--stt-model", default="small",
                        help="faster-whisper 모델 크기 (tiny/base/small/medium, 기본 small)")
    parser.add_argument("--no-tts", action="store_true", help="음성 출력(TTS) 끄기")
    args = parser.parse_args()

    model_name = BASE_MODEL if args.base else MINI_MODEL
    model, tokenizer, generation_config = load_model(model_name)
    stt = load_stt(args.stt_model) if args.voice else None

    tts_voice = None if args.no_tts else find_korean_voice()
    if not args.no_tts and tts_voice is None:
        print("(한국어 TTS 음성을 찾지 못해 음성 출력 없이 진행합니다.)")

    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    ask_consent = (lambda: listen(stt)) if stt is not None else (lambda: input().strip())
    agreed = consent.get_consent(
        ask_fn=ask_consent,
        speak_fn=lambda text: speak(text, tts_voice),
        channel="midm-local",
    )
    if not agreed:
        print(f"다솜이: {consent.DECLINE_FAREWELL}")
        speak(consent.DECLINE_FAREWELL, tts_voice)
        return

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": GREETING},
    ]

    print()
    print(f"다솜이: {GREETING}")
    speak(GREETING, tts_voice)

    drt_transcript: list[str] = []

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
            farewell = "오늘 이야기 나눠서 즐거웠어요. 또 전화드릴게요. 건강히 지내세요."
            print(f"다솜이: {farewell}")
            speak(farewell, tts_voice)
            break

        messages.append({"role": "user", "content": user_input})
        reply = generate_reply(model, tokenizer, generation_config, messages)
        reply, end_call = check_end_call(reply)
        messages.append({"role": "assistant", "content": reply})
        print(f"다솜이: {reply}")
        speak(reply, tts_voice)

        drt_transcript.append(f"어르신: {user_input}")
        drt_result = drt_analyzer.analyze_conversation("\n".join(drt_transcript))
        print(drt_analyzer.format_drt_summary(drt_result))

        if end_call:
            print("(통화를 마칩니다.)")
            break


if __name__ == "__main__":
    main()
