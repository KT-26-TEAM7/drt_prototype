"""Gemini 호출 어댑터.

두 가지 모드를 제공한다.

1. ``GeminiJointResponder``: 다솜이 답변과 DRT 의미 분석을 **한 번의 API 호출**로 반환
2. ``GeminiSemanticEnricher``: 로컬 Mi:dm 사용 시, 규칙으로 모호한 DRT 후보만 선택적으로 보강

Google SDK는 선택 의존성이다. API 키 또는 패키지가 없으면 호출하지 않고 상위 모듈이
규칙 기반으로 안전하게 폴백할 수 있도록 예외를 명확히 반환한다.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Sequence

from .config import Settings
from .schemas import DRTAnalysis, JointLLMResult, SessionState
from .taxonomy import CATEGORIES


class GeminiUnavailableError(RuntimeError):
    """Gemini SDK 또는 API 키가 준비되지 않은 경우."""


class GeminiCallError(RuntimeError):
    """Gemini 호출 또는 JSON 파싱이 실패한 경우."""


def _load_sdk() -> tuple[Any, Any]:
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:  # pragma: no cover - 설치 환경에서만 실행
        raise GeminiUnavailableError(
            "google-genai가 설치되지 않았습니다. pip install -r requirements-gemini.txt를 실행하세요."
        ) from exc
    return genai, types


def _clean_json_text(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _history_text(history: Sequence[dict[str, str]], limit: int = 10) -> str:
    lines: list[str] = []
    for item in list(history)[-limit:]:
        role = item.get("role", "")
        content = item.get("content", "").strip()
        if not content or role == "system":
            continue
        speaker = "다솜이" if role == "assistant" else "어르신"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def _semantic_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "visit_intent": {"type": "boolean"},
            "destination_category": {"type": "string", "enum": list(CATEGORIES)},
            "destination_candidates": {"type": "array", "items": {"type": "string"}},
            "specific_place": {"type": "string"},
            "place_preference": {
                "type": "string",
                "enum": ["unknown", "nearby", "frequent", "exact"],
            },
            "extracted_keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "visit_intent",
            "destination_category",
            "destination_candidates",
            "specific_place",
            "place_preference",
            "extracted_keywords",
        ],
        "additionalProperties": False,
    }


def _joint_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "assistant_reply": {"type": "string"},
            "end_call": {"type": "boolean"},
            "semantic": {
                "anyOf": [
                    _semantic_schema(),
                    {"type": "null"},
                ]
            },
        },
        "required": ["assistant_reply", "end_call", "semantic"],
        "additionalProperties": False,
    }


def _make_config(types: Any, *, schema: dict[str, Any], thinking_level: str) -> Any:
    """SDK 버전 차이를 흡수하면서 구조화 JSON과 낮은 추론 지연을 요청한다."""

    kwargs: dict[str, Any] = {
        "response_mime_type": "application/json",
        "response_json_schema": schema,
    }
    try:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)
    except (AttributeError, TypeError):
        pass

    try:
        return types.GenerateContentConfig(**kwargs)
    except TypeError:  # 구버전 SDK의 필드명
        kwargs.pop("response_json_schema", None)
        kwargs["response_schema"] = schema
        return types.GenerateContentConfig(**kwargs)


class _GeminiBase:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.settings.validate()
        if not self.settings.gemini_api_key:
            raise GeminiUnavailableError("GEMINI_API_KEY 또는 GEMINI_KEY가 설정되지 않았습니다.")
        genai, types = _load_sdk()
        self._types = types
        self._client = genai.Client(api_key=self.settings.gemini_api_key)

    def _generate(self, prompt: str, schema: dict[str, Any]) -> tuple[dict[str, Any], float]:
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.settings.gemini_model,
                contents=prompt,
                config=_make_config(
                    self._types,
                    schema=schema,
                    thinking_level=self.settings.gemini_thinking_level,
                ),
            )
            raw = _clean_json_text(getattr(response, "text", ""))
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JSON 객체가 아닙니다.")
            return payload, round((time.perf_counter() - started) * 1000, 3)
        except Exception as exc:  # pragma: no cover - 실제 API 환경
            raise GeminiCallError(f"Gemini 호출 실패: {type(exc).__name__}: {exc}") from exc


class GeminiSemanticEnricher(_GeminiBase):
    """규칙으로 모호한 DRT 후보 발화만 의미 보강한다."""

    def analyze(self, conversation: str) -> tuple[dict[str, Any] | None, float | None]:
        prompt = f"""
너는 고령층 케어콜에서 DRT 목적지 의미만 보강하는 분석기다.
반드시 지정된 JSON 구조만 출력한다.

허용 목적지 분류:
{", ".join(CATEGORIES)}

원칙:
- 날짜, 시간, 대화 단계, 누락 슬롯, 다음 질문, 예약 여부, 응급 여부는 만들지 않는다.
- 실제 발화에 나온 장소명만 specific_place에 기록한다.
- 발화에 없는 장소명을 절대 만들지 않는다.
- 가까운/근처는 nearby, 평소 다니는/자주 가는은 frequent로 표시한다.
- 확신이 없으면 unknown 또는 빈 배열/빈 문자열을 사용한다.

어르신 발화:
{conversation.strip()}
""".strip()
        payload, latency = self._generate(prompt, _semantic_schema())
        return payload, latency


class GeminiJointResponder(_GeminiBase):
    """다솜이 응답과 선택적 DRT 의미 분석을 한 번에 생성한다."""

    def respond(
        self,
        history: Sequence[dict[str, str]],
        user_text: str,
        *,
        drt_candidate: bool,
        analysis_hint: DRTAnalysis | None,
        state: SessionState,
    ) -> JointLLMResult:
        semantic_needed = bool(analysis_hint and analysis_hint.should_call_gemini)
        hint = {
            "dialogue_stage": analysis_hint.dialogue_stage if analysis_hint else None,
            "destination_category": analysis_hint.destination_category if analysis_hint else "unknown",
            "specific_place": analysis_hint.specific_place if analysis_hint else "",
            "place_preference": analysis_hint.place_preference if analysis_hint else "unknown",
            "target_slot": analysis_hint.target_slot if analysis_hint else None,
            "should_call_gemini": semantic_needed,
        }
        state_summary = {
            "destination_category": state.destination_category,
            "specific_place": state.specific_place,
            "place_preference": state.place_preference,
            "reservation_consent": state.reservation_consent,
            "date": state.date,
            "time": state.time,
            "pickup_location": state.pickup_location,
            "last_target_slot": state.last_target_slot,
        }
        prompt = f"""
너는 어르신의 다정한 안부 전화 말벗 '다솜이'다.
이번 요청에서는 다솜이의 짧은 응답과 DRT 의미 보강 결과를 한 번에 JSON으로 출력한다.

[말투]
- 공손한 존댓말과 쉬운 우리말을 사용한다.
- 한두 문장만 말한다.
- 어르신 말씀에 먼저 공감한다.
- 진단하거나 약을 추천하지 않는다.
- 돈, 계좌, 비밀번호를 묻지 않는다.
- 모르는 사실을 지어내지 않는다.

[질문 제어]
- DRT 후보가 참이면, 실제 다음 질문은 규칙 모듈이 붙인다.
  따라서 assistant_reply에는 공감 또는 짧은 확인 문장만 쓰고 물음표를 넣지 않는다.
- DRT 후보가 거짓이면 일상 케어콜 대화를 자연스럽게 이어가되 질문은 최대 하나만 한다.
- 어르신이 통화를 끝내려는 경우에만 end_call을 참으로 한다.

[DRT semantic]
- 의미 보강 필요가 참일 때만 semantic 객체를 채운다. 거짓이면 null을 출력한다.
- 허용 category: {", ".join(CATEGORIES)}
- 실제 발화에 포함된 고유 장소명만 specific_place에 기록한다.
- 발화에 없는 장소명은 절대 만들지 않는다.
- 안전, 예약 동의, 단계, 날짜, 시간, 다음 질문은 semantic에 넣지 않는다.

[규칙 모듈 참고값]
DRT 후보: {str(drt_candidate).lower()}
의미 보강 필요: {str(semantic_needed).lower()}
현재 규칙 판단: {json.dumps(hint, ensure_ascii=False)}
누적 DRT 상태: {json.dumps(state_summary, ensure_ascii=False)}

[최근 대화]
{_history_text(history)}
어르신: {user_text.strip()}
""".strip()

        try:
            payload, latency = self._generate(prompt, _joint_schema())
            semantic = payload.get("semantic") if isinstance(payload.get("semantic"), dict) else None
            return JointLLMResult(
                assistant_reply=str(payload.get("assistant_reply") or "").strip(),
                semantic=semantic,
                end_call=bool(payload.get("end_call", False)),
                latency_ms=latency,
                semantic_call_attempted=True,
            )
        except GeminiCallError:
            # 한 번 호출 원칙을 지키기 위해 같은 턴에 재호출하지 않는다.
            return JointLLMResult(
                assistant_reply="",
                semantic=None,
                end_call=False,
                latency_ms=None,
                semantic_call_attempted=True,
            )
