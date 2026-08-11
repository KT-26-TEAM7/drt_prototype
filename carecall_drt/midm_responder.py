"""김다솔 파트의 로컬 Mi:dm 2.0 케어콜 응답기."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .responses import END_CALL_MARKER, check_end_call
from .schemas import DRTAnalysis, JointLLMResult, SessionState

MINI_MODEL = "K-intelligence/Midm-2.0-Mini-Instruct"
BASE_MODEL = "K-intelligence/Midm-2.0-Base-Instruct"


class MidmCareResponder:
    def __init__(
        self,
        *,
        base_model: bool = False,
        prompt_path: str | Path | None = None,
        max_new_tokens: int = 128,
    ) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError(
                "Mi:dm 실행 의존성이 없습니다. pip install -r requirements-midm.txt를 실행하세요."
            ) from exc

        self.torch = torch
        self.max_new_tokens = max_new_tokens
        self.model_name = BASE_MODEL if base_model else MINI_MODEL
        default_prompt = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.txt"
        self.system_prompt = Path(prompt_path or default_prompt).read_text(encoding="utf-8")

        print(f"Mi:dm 모델 로딩 중... ({self.model_name})")
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=dtype,
            trust_remote_code=True,
            device_map="auto",
        )
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.generation_config = GenerationConfig.from_pretrained(self.model_name)

    def _generate(self, messages: list[dict[str, str]]) -> str:
        inputs = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.model.device)

        output = self.model.generate(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            generation_config=self.generation_config,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.eos_token_id,
            max_new_tokens=self.max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.05,
        )
        reply = self.tokenizer.decode(
            output[0][inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )
        return reply.strip()

    def respond(
        self,
        history: Sequence[dict[str, str]],
        user_text: str,
        *,
        drt_candidate: bool,
        analysis_hint: DRTAnalysis | None,
        state: SessionState,
    ) -> JointLLMResult:
        system = self.system_prompt
        if drt_candidate:
            system += (
                "\n\n[이번 턴 DRT 통합 지시]\n"
                "이동 관련 다음 질문은 프로그램이 별도로 붙인다. 이번 답변에는 질문을 넣지 말고, "
                "어르신 말씀에 대한 짧은 공감 문장 하나만 말한다. 장소나 예약 정보를 지어내지 않는다."
            )
        messages = [{"role": "system", "content": system}]
        messages.extend(item for item in history if item.get("role") in {"user", "assistant"})
        messages.append({"role": "user", "content": user_text})
        raw = self._generate(messages)
        reply, ended = check_end_call(raw)
        return JointLLMResult(
            assistant_reply=reply,
            semantic=None,
            end_call=ended,
            semantic_call_attempted=False,
        )
