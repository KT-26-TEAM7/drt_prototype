'''LoRA로 파인튜닝한 Mi:dm 2.0 Mini와 터미널에서 대화해보는 데모.

chat_demo.py와 거의 동일하지만, 베이스 모델 위에 finetune/train_lora.py로 학습한
LoRA 어댑터를 얹어서 로드합니다. 같은 system_prompt.txt를 사용하므로
파인튜닝 전(chat_demo.py)과 후(이 스크립트)의 응답을 비교해보기 좋습니다.

실행:
    python finetune/chat_finetuned.py
    python finetune/chat_finetuned.py --adapter finetune/output/midm-lora
    python finetune/chat_finetuned.py --no-tts
'''

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

BASE_MODEL = "K-intelligence/Midm-2.0-Mini-Instruct"
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
GREETING = "안녕하세요, 어르신. 말벗 다솜이예요. 요즘 잘 지내고 계세요?"


def load_model(adapter_path: str):
    print(f"베이스 모델 로딩 중... ({BASE_MODEL})")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, trust_remote_code=True, dtype=dtype, low_cpu_mem_usage=True,
    ).to(device)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)

    print(f"LoRA 어댑터 로딩 중... ({adapter_path})")
    model = PeftModel.from_pretrained(model, adapter_path)
    model.eval()

    try:
        generation_config = GenerationConfig.from_pretrained(BASE_MODEL)
    except Exception:  # noqa: BLE001
        generation_config = GenerationConfig()
    return model, tokenizer, generation_config


def generate_reply(model, tokenizer, generation_config, messages) -> str:
    inputs = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True,
        return_dict=True, return_tensors="pt",
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
    parser = argparse.ArgumentParser(description="파인튜닝된 Mi:dm 케어콜 챗봇 데모")
    parser.add_argument("--adapter", default="finetune/output/midm-lora", help="LoRA 어댑터 경로")
    parser.add_argument("--no-tts", action="store_true", help="음성 출력(TTS) 끄기")
    args = parser.parse_args()

    model, tokenizer, generation_config = load_model(args.adapter)

    tts_voice = None if args.no_tts else find_korean_voice()
    if not args.no_tts and tts_voice is None:
        print("(한국어 TTS 음성을 찾지 못해 음성 출력 없이 진행합니다.)")

    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": GREETING},
    ]

    print()
    print(f"다솜이(파인튜닝): {GREETING}")
    speak(GREETING, tts_voice)

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
            print(f"다솜이(파인튜닝): {farewell}")
            speak(farewell, tts_voice)
            break

        messages.append({"role": "user", "content": user_input})
        reply = generate_reply(model, tokenizer, generation_config, messages)
        messages.append({"role": "assistant", "content": reply})
        print(f"다솜이(파인튜닝): {reply}")
        speak(reply, tts_voice)


if __name__ == "__main__":
    main()
