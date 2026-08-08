'''Midm-2.0-Mini-Instruct LoRA 파인튜닝 (macOS Apple Silicon / MPS 기준).

입력: finetune/prepare_dataset.py로 만든 JSONL
    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, ...]}

각 assistant 턴의 토큰에만 loss를 걸고(user/system 프롬프트 부분은 -100으로 마스킹),
나머지 구간은 학습에서 제외합니다.

실행:
    python finetune/train_lora.py --data finetune/data/train.jsonl --epochs 3
    python finetune/train_lora.py --data finetune/data/train.jsonl --dtype float32   # 메모리 여유 있을 때
'''

import argparse
import json
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

MODEL_NAME = "K-intelligence/Midm-2.0-Mini-Instruct"
MAX_LENGTH = 1024


def load_examples(path: Path) -> list[list[dict]]:
    examples = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line)["messages"])
    return examples


def tokenize_with_masked_labels(messages: list[dict], tokenizer) -> dict:
    '''전체 대화를 토큰화하고, assistant 턴 구간에만 label을 남긴다.

    tokenizer.apply_chat_template(messages[:i])가 apply_chat_template(messages)의
    접두(prefix)라는 가정에 의존한다 (대부분의 채팅 템플릿은 턴을 이어 붙이는
    방식이라 성립하지만, 100% 보장은 아니므로 완벽하지 않을 수 있다).
    '''
    full_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False
    )
    labels = [-100] * len(full_ids)

    prev_len = len(
        tokenizer.apply_chat_template([], tokenize=True, add_generation_prompt=False)
    ) if messages else 0

    for i in range(1, len(messages) + 1):
        cur_ids = tokenizer.apply_chat_template(
            messages[:i], tokenize=True, add_generation_prompt=False
        )
        cur_len = len(cur_ids)
        if messages[i - 1]["role"] == "assistant":
            end = min(cur_len, len(full_ids))
            for j in range(prev_len, end):
                labels[j] = full_ids[j]
        prev_len = cur_len

    full_ids = full_ids[:MAX_LENGTH]
    labels = labels[:MAX_LENGTH]
    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": labels,
    }


def find_target_modules(model) -> list[str]:
    names = set()
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Linear) and name.split(".")[-1].endswith("proj"):
            names.add(name.split(".")[-1])
    return sorted(names) or ["q_proj", "k_proj", "v_proj", "o_proj"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mi:dm 2.0 Mini LoRA 파인튜닝")
    parser.add_argument("--data", default="finetune/data/train.jsonl")
    parser.add_argument("--output", default="finetune/output/midm-lora")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument(
        "--dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"],
        help="베이스 모델 로드 dtype. 메모리가 부족하면 float16, 불안정하면 float32 시도",
    )
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        raise SystemExit(f"학습 데이터가 없습니다: {data_path} (먼저 prepare_dataset.py를 실행하세요)")

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"device: {device}")

    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[args.dtype]

    print("토크나이저/모델 로딩 중...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, trust_remote_code=True, dtype=dtype, low_cpu_mem_usage=True,
    )
    model.to(device)

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=find_target_modules(model),
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    raw_examples = load_examples(data_path)
    print(f"학습 샘플 {len(raw_examples)}개 로딩됨. 토큰화 중...")
    tokenized = [tokenize_with_masked_labels(messages, tokenizer) for messages in raw_examples]
    dataset = Dataset.from_list(tokenized)

    collator = DataCollatorForSeq2Seq(
        tokenizer, model=model, padding=True, label_pad_token_id=-100,
    )

    training_args = TrainingArguments(
        output_dir=args.output,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        report_to=[],
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=collator,
    )

    trainer.train()

    print(f"LoRA 어댑터 저장 중: {args.output}")
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    print("완료.")


if __name__ == "__main__":
    main()
