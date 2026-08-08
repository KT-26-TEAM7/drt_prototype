'''AI Hub 복지 분야 콜센터 상담데이터(JSON 전사) → Mi:dm 파인튜닝용 JSONL 변환.

AI Hub 라벨링데이터의 정확한 JSON 스키마는 기관/버전에 따라 조금씩 다르므로,
아래 SPEAKER_KEYS / TEXT_KEYS 후보 목록으로 자동 탐지를 시도합니다.
`python finetune/inspect_sample.py`로 실제 구조를 먼저 확인한 뒤,
자동 탐지가 안 맞으면 이 파일 상단의 후보 목록에 실제 키 이름을 추가하세요.

내담자(고객) 발화 -> user, 상담사 발화 -> assistant 로 매핑해서
이 프로젝트의 케어콜 상담 페르소나("다솜이") 톤에 맞는 멀티턴 대화로 만듭니다.

실행:
    python finetune/prepare_dataset.py finetune/data/raw --out finetune/data/train.jsonl
'''

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

# 실제 데이터를 inspect_sample.py로 확인한 뒤 필요하면 여기에 키를 추가하세요.
TEXT_KEYS = [
    "발화문", "발화내용", "utterance", "text", "transcription", "stt", "content",
    "sentence", "script", "standard", "answer", "originalText",
]
SPEAKER_KEYS = [
    "화자", "화자명", "speaker", "speakerRole", "역할", "발화자", "role", "spkRole", "speakerType",
]

COUNSELOR_HINTS = ["상담사", "상담원", "counselor", "agent", "cnslr", "operator"]
CUSTOMER_HINTS = ["고객", "내담자", "민원인", "customer", "caller", "client", "user"]

# 이 프로젝트의 케어콜 페르소나에 맞춘 시스템 프롬프트.
# prompts/system_prompt.txt와 결을 맞추되, 상담 도메인 지식을 담기 위해
# 학습 데이터 특성(복지 상담)에 맞게 축약된 버전을 사용합니다.
SYSTEM_PROMPT = (
    "너는 어르신을 위한 말벗이자 복지 상담사 '다솜이'다. "
    "따뜻하고 공손한 존댓말로, 한 번에 1~2문장만 짧게 말한다. "
    "의료 진단이나 약 처방은 하지 않고, 필요하면 병원/복지 서비스 방문을 권한다. "
    "이동이 어렵다는 말이 나오면 이동지원(DRT) 이용 의사를 확인한다."
)

MIN_CHARS = 2
MAX_CHARS = 300


def find_json_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.json"))


def find_utterance_list(node: Any) -> Optional[list[dict]]:
    """재귀적으로 '발화 리스트'로 보이는 list[dict]를 찾는다."""
    if isinstance(node, list) and node and all(isinstance(item, dict) for item in node):
        sample = node[0]
        has_text = any(key in sample for key in TEXT_KEYS)
        if has_text:
            return node
    if isinstance(node, dict):
        for value in node.values():
            found = find_utterance_list(value)
            if found is not None:
                return found
    if isinstance(node, list):
        for item in node:
            found = find_utterance_list(item)
            if found is not None:
                return found
    return None


def get_first(d: dict, keys: list[str]) -> Optional[str]:
    for key in keys:
        if key in d and d[key] is not None:
            value = d[key]
            return str(value).strip()
    return None


def classify_role(speaker_raw: str) -> Optional[str]:
    lowered = speaker_raw.lower()
    if any(hint in lowered or hint in speaker_raw for hint in COUNSELOR_HINTS):
        return "assistant"
    if any(hint in lowered or hint in speaker_raw for hint in CUSTOMER_HINTS):
        return "user"
    return None


def build_messages(utterances: list[dict]) -> Optional[list[dict]]:
    turns: list[dict] = []
    fallback_role = "user"  # 화자 라벨을 못 찾으면 번갈아가며 배정

    for utt in utterances:
        text = get_first(utt, TEXT_KEYS)
        if not text or not (MIN_CHARS <= len(text) <= MAX_CHARS):
            continue

        speaker_raw = get_first(utt, SPEAKER_KEYS)
        role = classify_role(speaker_raw) if speaker_raw else None
        if role is None:
            role = fallback_role
            fallback_role = "assistant" if fallback_role == "user" else "user"

        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += " " + text
        else:
            turns.append({"role": role, "content": text})

    # user로 시작해서 assistant로 끝나는 멀티턴만 채택 (학습 라벨 = assistant 턴)
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    while turns and turns[-1]["role"] != "assistant":
        turns.pop()

    if len(turns) < 2:
        return None

    return [{"role": "system", "content": SYSTEM_PROMPT}] + turns


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Hub 상담 JSON -> 파인튜닝 JSONL 변환")
    parser.add_argument("root", help="JSON이 들어있는 폴더")
    parser.add_argument("--out", default="finetune/data/train.jsonl", help="출력 JSONL 경로")
    parser.add_argument("--max-samples", type=int, default=3000, help="최대 대화(샘플) 개수")
    args = parser.parse_args()

    root = Path(args.root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = find_json_files(root)
    if not files:
        print(f"{root} 아래에서 .json 파일을 찾지 못했습니다.")
        sys.exit(1)

    written = 0
    skipped_no_list = 0
    skipped_short = 0

    with out_path.open("w", encoding="utf-8") as out_f:
        for path in files:
            if written >= args.max_samples:
                break
            try:
                with path.open(encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                continue

            utterances = find_utterance_list(data)
            if utterances is None:
                skipped_no_list += 1
                continue

            messages = build_messages(utterances)
            if messages is None:
                skipped_short += 1
                continue

            out_f.write(json.dumps({"messages": messages}, ensure_ascii=False) + "\n")
            written += 1

    print(f"완료: {written}개 대화 샘플을 {out_path}에 저장했습니다.")
    print(f"(발화 리스트를 못 찾아 건너뜀: {skipped_no_list}개, 너무 짧아 건너뜀: {skipped_short}개)")
    if written == 0:
        print(
            "\n0개가 저장되었습니다. finetune/inspect_sample.py로 실제 JSON 구조를 확인한 뒤 "
            "이 파일 상단의 TEXT_KEYS / SPEAKER_KEYS / COUNSELOR_HINTS / CUSTOMER_HINTS를 "
            "실제 키·값에 맞게 수정해주세요."
        )


if __name__ == "__main__":
    main()
