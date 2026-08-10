"""drt_service 응답을 어르신께 읽어 드릴 한국어 문장으로 바꾼다.

care-call-bot의 prompts/system_prompt.txt가 정한 음성 규칙을 그대로 따른다.
- 한 번에 한두 문장, 질문은 하나만
- 이모지·특수문자·영어·한자 금지 (TTS로 읽히기 때문)

특히 "DRT"는 영어라서 그대로 읽으면 안 된다. 어르신께는 "이동 차량"이라고 말한다.
모델 비교 과정에서 LLM이 답변 끝에 한자를 흘린 사례가 있어서, 문장을 만든 뒤
실제로 위반이 없는지 `tts_violations()`로 검사할 수 있게 해 두었다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 되물어야 하는 답변의 종류. orchestrator가 다음 턴에 무엇을 기다릴지 정하는 데 쓴다.
EXPECT_NONE = ""
EXPECT_DESTINATION_CHOICE = "destination_choice"
EXPECT_RESERVATION_CONFIRM = "reservation_confirm"

# 음성으로 읽으면 안 되는 표현 -> 대체 표현.
TERM_REPLACEMENTS = (
    ("DRT", "이동 차량"),
    ("drt", "이동 차량"),
    ("TMAP", "길 안내"),
    ("API", "연결"),
    ("GPS", "위치"),
)

_HANJA = r"一-鿿"
_EMOJI = r"\U0001f300-\U0001faff☀-➿"
_LATIN = r"A-Za-z"

# 한자와 이모지는 어떤 경우에도 읽을 이유가 없으므로 지운다.
_STRIPPED = re.compile(f"[{_HANJA}{_EMOJI}]")
# 영문자는 지우지 않는다. "지에스편의점"으로 바꿔 읽어야 하는 건 맞지만,
# 목적지 이름에 들어 있는 영문(예: 케이티, 지에스)을 지워 버리면 어느 곳인지
# 알 수 없게 되기 때문이다. 대신 위반으로 보고해서 로그에 남긴다.
_FLAGGED = re.compile(f"[{_HANJA}{_EMOJI}{_LATIN}]")


@dataclass(frozen=True, slots=True)
class Utterance:
    """어르신께 읽어 드릴 한 마디."""

    text: str
    expects: str = EXPECT_NONE
    kind: str = "info"


def tts_violations(text: str) -> list[str]:
    """음성 규칙을 어긴 문자들을 돌려준다(비어 있으면 안전).

    목적지 고유명사에서 온 영문자는 지우지 않지만 여기에는 잡힌다. 브릿지가 만든
    문장에서 잡히면 문구를 고쳐야 하고, 목적지 이름에서 온 것이면 그대로 두면 된다.
    """
    return sorted(set(_FLAGGED.findall(text)))


def sanitize(text: str) -> str:
    """음성으로 읽을 수 있게 다듬는다. 알려진 용어는 바꾸고, 한자·이모지는 지운다."""
    cleaned = text or ""
    for term, replacement in TERM_REPLACEMENTS:
        cleaned = cleaned.replace(term, replacement)
    cleaned = _STRIPPED.sub("", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def say(text: str, expects: str = EXPECT_NONE, kind: str = "info") -> Utterance:
    return Utterance(sanitize(text), expects, kind)


def _minutes(seconds: Any) -> int | None:
    if not isinstance(seconds, (int, float)):
        return None
    return max(1, round(seconds / 60))


def direction_particle(word: str) -> str:
    """"...로" / "...으로"를 고른다.

    받침이 없거나 받침이 'ㄹ'이면 "로", 그 밖에는 "으로"다. TTS로 읽히므로
    "정형외과으로"처럼 틀리면 바로 귀에 걸린다.
    """
    if not word or not ("가" <= word[-1] <= "힣"):
        return "로"
    final_consonant = (ord(word[-1]) - ord("가")) % 28
    return "로" if final_consonant in (0, 8) else "으로"


def topic_particle(word: str) -> str:
    """"...은" / "...는"을 고른다."""
    if not word or not ("가" <= word[-1] <= "힣"):
        return "는"
    return "은" if (ord(word[-1]) - ord("가")) % 28 else "는"


def _arrival_phrase(seconds: Any) -> str:
    """차량 도착까지 남은 시간을 말로 표현한다.

    1분 미만을 "약 0분"이나 "약 1분"으로 읽으면 어르신이 시계를 보고 기다리시게
    되므로, 그 구간은 "곧"으로 뭉뚱그린다.
    """
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return ""
    if seconds < 60:
        return "곧"
    return f"약 {round(seconds / 60)}분 뒤에"


def _name(node: Any, default: str = "목적지") -> str:
    if isinstance(node, dict):
        value = node.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _join_candidates(candidates: list[dict], limit: int) -> str:
    names = [_name(item, "") for item in candidates[:limit]]
    return ", ".join(name for name in names if name)


def spoken_for_plan(plan: dict[str, Any], *, max_candidates: int = 3) -> Utterance:
    """`/api/plan` 응답의 plan 본문을 음성 문장으로 바꾼다."""
    status = str(plan.get("status") or "")
    destination = _name(plan.get("destination"))

    if status == "ready_for_confirmation":
        total = _minutes(plan.get("total_travel_time_s"))
        boarding = _name(plan.get("boarding"), "")
        시간안내 = f"타고 내리는 시간까지 해서 약 {total}분 걸려요. " if total else ""
        출발안내 = f"{boarding}에서 차를 타시면 돼요. " if boarding else ""
        return say(
            f"{destination}{direction_particle(destination)} 가시는 길을 찾았어요. "
            f"{출발안내}{시간안내}차를 불러 드릴까요?",
            EXPECT_RESERVATION_CONFIRM,
            "plan_ready",
        )

    if status == "walk_recommended":
        walk = _minutes((plan.get("direct_walk") or {}).get("duration_s"))
        걸리는시간 = f" 걸어서 약 {walk}분이면 되세요." if walk else ""
        return say(
            f"{destination}{topic_particle(destination)} 가까워서 "
            f"차를 부르지 않으셔도 될 것 같아요.{걸리는시간}",
            EXPECT_NONE,
            "walk_recommended",
        )

    if status == "needs_destination_confirmation":
        candidates = plan.get("candidates") or []
        listed = _join_candidates(candidates, max_candidates)
        return say(
            f"비슷한 곳이 여러 군데 있어요. {listed} 중에 어디로 모실까요?",
            EXPECT_DESTINATION_CHOICE,
            "needs_choice",
        )

    # 아래 세 가지는 되묻기는 하지만 EXPECT_DESTINATION_CHOICE를 걸지 않는다.
    # 고를 후보가 없어서 어르신이 새 목적지를 말씀하시게 되는데, 자유 발화에서
    # 목적지를 뽑는 일은 케어콜 분석기의 몫이기 때문이다. 다음 턴의 분석 결과가
    # handle_analysis로 다시 들어오면 된다.
    if status == "destination_not_found":
        return say(
            "말씀하신 곳을 찾지 못했어요. 이름을 한 번만 더 말씀해 주시겠어요?",
            EXPECT_NONE,
            "not_found",
        )

    if status == "destination_outside_service_area":
        return say(
            "그곳은 이동 차량이 다니지 않는 지역이에요. 다른 곳을 말씀해 주시겠어요?",
            EXPECT_NONE,
            "out_of_area",
        )

    if status == "no_feasible_destination":
        return say(
            "가까운 곳에서는 마땅한 데를 찾지 못했어요. 다른 곳을 말씀해 주시겠어요?",
            EXPECT_NONE,
            "no_candidate",
        )

    if status == "outside_service_area":
        return say(
            "지금 계신 곳은 아직 이동 차량이 다니지 않는 지역이에요. 도움이 못 되어 죄송해요.",
            EXPECT_NONE,
            "out_of_area",
        )

    if status == "no_accessible_boarding_station":
        return say(
            "가까운 승차 장소가 걸어가시기에는 조금 멀어요. 다른 방법을 알아봐 드릴까요?",
            EXPECT_NONE,
            "no_station",
        )

    if status in ("route_api_failed", "destination_search_failed"):
        return say(
            "지금 길 찾기가 잘 되지 않네요. 잠시 뒤에 다시 알아봐 드릴게요.",
            EXPECT_NONE,
            "temporary_failure",
        )

    return say(
        "차편을 알아보는 데 문제가 있었어요. 잠시 뒤에 다시 도와드릴게요.",
        EXPECT_NONE,
        "unknown_status",
    )


def spoken_for_reservation(response: dict[str, Any], boarding_name: str = "") -> Utterance:
    """`/api/reservations` 응답을 음성 문장으로 바꾼다.

    call_id와 조회 링크는 읽지 않는다. 전화로 들으신 어르신이 받아 적을 수 없는
    값이라, 링크는 문자로 보내고(bridge/notify.py) 말로는 도착 시간만 알려 드린다.
    """
    reservation = response.get("reservation")
    if response.get("ok") and isinstance(reservation, dict):
        장소 = f"{boarding_name}에서 " if boarding_name else ""
        # 배차 서버가 붙어 있으면 실제 도착예정시간을 알려 드릴 수 있다.
        도착 = _arrival_phrase(reservation.get("estimated_arrival_s"))
        if 도착:
            return say(f"차를 불러 드렸어요. {장소}{도착} 차가 도착해요.", EXPECT_NONE, "reserved")
        return say(
            f"차를 불러 드렸어요. {장소}조금만 기다려 주세요.",
            EXPECT_NONE,
            "reserved",
        )

    if response.get("ok") and reservation is None:
        # 도보 추천이라 예약이 필요 없다고 판단된 경우.
        return say("걸어가셔도 되는 거리라 차는 부르지 않았어요.", EXPECT_NONE, "walk_recommended")

    return say(
        "지금은 차를 부르지 못했어요. 잠시 뒤에 다시 도와드릴게요.",
        EXPECT_NONE,
        "reservation_failed",
    )


def guardian_message(
    elder_name: str, destination: str, boarding_name: str = "", total_minutes: int | None = None
) -> str:
    """보호자에게 보낼 알림 문구.

    보호자는 글로 읽으므로 음성 규칙(문장 수 제한)을 적용하지 않는다. 다만 이 문구를
    실제로 보내는 일은 브릿지 밖(알림 채널)의 몫이다 — drt_service에는 보호자 알림
    API가 없다.
    """
    parts = [f"{elder_name} 어르신의 이동 차량이 예약되었습니다."]
    if boarding_name:
        parts.append(f"승차 장소는 {boarding_name}입니다.")
    parts.append(f"목적지는 {destination}입니다.")
    if total_minutes:
        parts.append(f"예상 소요 시간은 약 {total_minutes}분입니다.")
    return " ".join(parts)
