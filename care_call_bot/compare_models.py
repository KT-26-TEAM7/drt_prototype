"""Mi:dm 2.0(로컬) vs Gemini API 비교 테스트.

같은 시나리오(짧은 대답, 건강 호소, 외로움 호소, 통화 종료 유도)를 두 모델에
똑같이 순서대로 넣어보고, 답변 내용·응답 시간·말투 규칙 위반 여부를 나란히 기록한다.

동의(consent) 절차는 비교 테스트 목적이라 건너뛴다 — 두 모델의 대화 능력만 비교한다.

실행:
    python compare_models.py                 # 로컬 Mi:dm + Gemini 둘 다
    python compare_models.py --skip-local     # Gemini만 먼저 빠르게 보고 싶을 때
    python compare_models.py --out compare_result.json
"""

import argparse
import json
import re
import time
from pathlib import Path

from google.genai import types

import chat_demo
import gemini_chat_demo

SYSTEM_PROMPT = chat_demo.SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

# 실제 케어콜에서 나올 법한 흐름: 짧은 대답 -> 건강 호소 -> 외로움 호소 -> 통화 종료 유도.
# system_prompt.txt의 규칙(말투, 공감 우선, 진단 금지, 통화 종료 마커)이
# 두 모델에서 얼마나 다르게 지켜지는지 보기 위한 시나리오.
SCENARIO = [
    "그냥 그렇지 뭐.",
    "요즘 무릎이 아파서 잠을 잘 못 자.",
    "자식들이 통 연락이 없어서 적적해.",
    "이제 그만 끊을게.",
]

# 음성으로 읽히는 대화라 이모지/영어/한자를 쓰면 안 된다는 규칙(system_prompt.txt) 위반 여부를
# 대략적으로 자동 점검한다. 완벽한 검사는 아니고 참고용 신호다.
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF☀-➿]"
)
LATIN_PATTERN = re.compile(r"[a-zA-Z]")
HANJA_PATTERN = re.compile(r"[一-鿿]")


def check_tone_violations(text: str) -> list[str]:
    violations = []
    if EMOJI_PATTERN.search(text):
        violations.append("이모지 포함")
    if LATIN_PATTERN.search(text):
        violations.append("영어 알파벳 포함")
    if HANJA_PATTERN.search(text):
        violations.append("한자 포함")
    if len(text) > 120:
        violations.append("한 번에 너무 길게 말함")
    return violations


def run_midm(scenario: list[str]) -> list[dict]:
    print("Mi:dm 2.0 Mini 로딩 중...")
    model, tokenizer, generation_config = chat_demo.load_model(chat_demo.MINI_MODEL)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": chat_demo.GREETING},
    ]

    results = []
    for turn in scenario:
        messages.append({"role": "user", "content": turn})
        start = time.time()
        raw_reply = chat_demo.generate_reply(model, tokenizer, generation_config, messages)
        elapsed = time.time() - start
        reply, end_call = chat_demo.check_end_call(raw_reply)
        messages.append({"role": "assistant", "content": reply})
        results.append({
            "user": turn,
            "reply": reply,
            "elapsed_sec": round(elapsed, 2),
            "end_call_marker": end_call,
            "tone_violations": check_tone_violations(reply),
        })
    return results


def run_gemini(scenario: list[str], model_name: str) -> list[dict]:
    print(f"Gemini API 호출 준비 중... ({model_name})")
    client = gemini_chat_demo.load_client()
    chat = client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        history=[types.Content(role="model", parts=[types.Part(text=chat_demo.GREETING)])],
    )

    results = []
    for turn in scenario:
        start = time.time()
        response = chat.send_message(turn)
        elapsed = time.time() - start
        reply, end_call = gemini_chat_demo.check_end_call(response.text or "")
        results.append({
            "user": turn,
            "reply": reply,
            "elapsed_sec": round(elapsed, 2),
            "end_call_marker": end_call,
            "tone_violations": check_tone_violations(reply),
        })
    return results


def print_report(midm_results: list[dict] | None, gemini_results: list[dict]) -> None:
    for i, turn in enumerate(SCENARIO):
        print("=" * 70)
        print(f"[{i + 1}] 어르신: {turn}")
        if midm_results is not None:
            r = midm_results[i]
            flag = f" ({', '.join(r['tone_violations'])})" if r["tone_violations"] else ""
            print(f"  Mi:dm   [{r['elapsed_sec']}초]{flag}: {r['reply']}")
        r = gemini_results[i]
        flag = f" ({', '.join(r['tone_violations'])})" if r["tone_violations"] else ""
        print(f"  Gemini  [{r['elapsed_sec']}초]{flag}: {r['reply']}")
    print("=" * 70)

    if midm_results is not None:
        midm_avg = sum(r["elapsed_sec"] for r in midm_results) / len(midm_results)
        print(f"평균 응답시간 — Mi:dm: {midm_avg:.2f}초", end="  ")
    gemini_avg = sum(r["elapsed_sec"] for r in gemini_results) / len(gemini_results)
    print(f"Gemini: {gemini_avg:.2f}초")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mi:dm vs Gemini 비교 테스트")
    parser.add_argument("--skip-local", action="store_true", help="로컬 Mi:dm은 건너뛰고 Gemini만 실행")
    parser.add_argument("--model", default=gemini_chat_demo.DEFAULT_MODEL, help="Gemini 모델명")
    parser.add_argument("--out", default="compare_result.json", help="결과 JSON 저장 경로")
    args = parser.parse_args()

    midm_results = None if args.skip_local else run_midm(SCENARIO)
    gemini_results = run_gemini(SCENARIO, args.model)

    print_report(midm_results, gemini_results)

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps({"midm": midm_results, "gemini": gemini_results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n결과를 {out_path}에 저장했습니다.")


if __name__ == "__main__":
    main()
