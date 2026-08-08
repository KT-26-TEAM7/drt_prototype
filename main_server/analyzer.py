"""케어콜 분석기(`care_call_bot/drt_analyzer.py`) 어댑터.

메인 서버는 대화를 소유하므로 분석기를 직접 부른다(브릿지는 부르지 않는다 —
브릿지는 출력 JSON만 계약으로 삼는 계층이라 그대로 둔다).

**한 번에 최신 발화 한 마디만** 넘긴다. 대화 전체를 넘기면 분석기가 매번 전체를
다시 해석하면서 앞선 발화가 나중 발화를 이기는 문제가 생긴다(conversation.py 설명 참고).

분석기를 못 불러와도 서버는 죽지 않는다. 규칙 기반 최소 분석으로 계속 동작한다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ANALYZER_DIR = PROJECT_DIR / "care_call_bot"


class AnalyzerUnavailable(RuntimeError):
    """분석기를 불러오지 못했다."""


def load_analyzer(analyzer_dir: Path | str | None = None) -> Callable[[str], dict[str, Any]]:
    """`analyze_conversation` 함수를 돌려준다.

    care_call_bot은 이 작업공간 안에 함께 있으므로 경로를 따로 줄 필요가 없다.
    """
    directory = Path(analyzer_dir or DEFAULT_ANALYZER_DIR)
    if not (directory / "drt_analyzer.py").exists():
        raise AnalyzerUnavailable(f"drt_analyzer.py를 찾지 못했습니다: {directory}")

    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        import drt_analyzer  # type: ignore
    except ModuleNotFoundError as exc:
        raise AnalyzerUnavailable(
            f"분석기를 불러오지 못했습니다({exc.name} 없음). "
            "py scripts/setup.py 를 실행했는지 확인하세요."
        ) from exc
    return drt_analyzer.analyze_conversation


# ── 분석기가 없을 때 쓰는 최소 규칙 ──────────────────────────────────────
#
# 분석기(그리고 Gemini)를 못 쓰는 환경에서도 흐름을 확인할 수 있도록 아주 얕은
# 규칙만 둔다. 실제 판정 품질은 분석기 쪽이 훨씬 낫다.

_FALLBACK_PLACES = (
    ("medical_dental", "치과"), ("medical_orthopedics", "정형외과"),
    ("medical_general", "병원"), ("pharmacy", "약국"),
    ("shopping_market", "시장"), ("shopping_mart", "마트"),
    ("senior_center", "경로당"), ("welfare_center", "복지관"),
    ("leisure_library", "도서관"), ("public_bank", "은행"),
)
_FALLBACK_RESERVE = ("불러줘", "불러 줘", "예약해줘", "예약해 줘", "해줘", "그래", "응", "네")
_FALLBACK_REFUSE = ("안 불러도", "안불러도", "집에 있을래", "집에서 쉴래", "취소", "됐어", "아니")
_FALLBACK_EMERGENCY = ("넘어졌", "못 일어나", "숨이 차", "가슴이 답답", "쓰러")


def fallback_analyze(utterance: str) -> dict[str, Any]:
    """분석기 없이 쓰는 얕은 규칙 분석. 모양은 분석기 출력과 같게 맞춘다."""
    text = re.sub(r"(어르신|상담사)\s*:", " ", utterance or "").strip()
    compact = re.sub(r"\s+", "", text)

    if any(word in compact for word in (w.replace(" ", "") for w in _FALLBACK_EMERGENCY)):
        return _shape(stage="emergency", emergency=True)
    if any(word in compact for word in (w.replace(" ", "") for w in _FALLBACK_REFUSE)):
        return _shape(stage="not_needed", consent="refused")

    category = place = ""
    for key, word in _FALLBACK_PLACES:
        if word in text:
            category, place = key, word
            break

    wants_car = any(word.replace(" ", "") in compact for word in _FALLBACK_RESERVE)
    if category and wants_car:
        return _shape(stage="reservation_info_collection", consent="confirmed",
                      category=category, place=place)
    if category:
        return _shape(stage="reservation_confirm", category=category, place=place)
    if wants_car:
        return _shape(stage="reservation_info_collection", consent="confirmed")
    return _shape(stage="need_detection")


def _shape(
    *, stage: str, consent: str = "not_confirmed", emergency: bool = False,
    category: str = "", place: str = "",
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "dialogue_stage": stage,
        "drt_status": "unclear",
        "destination_category": category or "unknown",
        "destination_candidates": [place] if place else [],
        "search_keywords": [place] if place else [],
        "search_mode": "nearby_search" if place else "not_applicable",
        "place_resolution_required": False,
        "place_resolution_question": "",
        "missing_slots": ["date", "time", "pickup_location"] if stage == "reservation_info_collection" else [],
        "reservation_consent": consent,
        "guardian_notify_consent": "not_asked",
        "mobility_difficulty": False,
        "emergency_risk": emergency,
        "extracted_keywords": [place] if place else [],
        "next_question": "",
        "_source": "fallback_rules",
    }
    if stage == "need_detection":
        output["missing_slots"] = ["visit_intent", "reservation_consent"]
    return output
