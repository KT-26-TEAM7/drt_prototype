"""통화 한 건 동안 유지되는 브릿지 상태.

DRT 예약은 한 번의 발화로 끝나지 않는다. "어느 치과요?" -> "연세치과" 처럼
되묻고 답을 받는 과정이 있어서, 무엇을 기다리는 중인지 기억해야 한다.

지금은 메모리 저장이다. 실제 서비스에서는 통화 세션 저장소(Redis 등)로 바뀐다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# "첫 번째" 같은 서수 표현 -> 인덱스.
_ORDINALS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("첫번째", "첫째", "처음", "1번", "일번", "하나"), 0),
    (("두번째", "둘째", "2번", "이번째", "이번", "둘"), 1),
    (("세번째", "셋째", "3번", "삼번", "셋"), 2),
)

_YES = ("응", "네", "예", "그래", "좋아", "해줘", "해 줘", "부탁", "그렇게", "맞아", "알겠")
_NO = ("아니", "싫", "안 해", "안해", "괜찮아", "됐어", "그만", "취소", "말아")

# 어르신은 "연세치과로 가자"처럼 이름 뒤에 조사를 붙여 답하신다. 이름만 남기려면 떼어내야 한다.
# 긴 조사를 먼저 검사해야 "으로"가 "로"로 잘못 잘리지 않는다.
_PARTICLES = ("으로", "에서", "까지", "이요", "로", "에", "은", "는", "이", "가", "을", "를", "도", "만", "요")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _name_tokens(text: str) -> list[str]:
    """발화에서 장소 이름이 될 만한 토막을 뽑는다(조사 제거, 두 글자 이상)."""
    tokens: list[str] = []
    for raw in re.split(r"[\s,./]+", text or ""):
        cleaned = re.sub(r"[^가-힣A-Za-z0-9]", "", raw)
        for particle in _PARTICLES:
            # 조사를 떼고도 두 글자 이상 남을 때만 뗀다.
            if cleaned.endswith(particle) and len(cleaned) - len(particle) >= 2:
                cleaned = cleaned[: -len(particle)]
                break
        if len(cleaned) >= 2:
            tokens.append(cleaned)
    return tokens


def parse_yes_no(text: str) -> bool | None:
    """동의/거절/판단불가(None)로 나눈다.

    care-call-bot의 consent.py와 같은 방식이다. 거절을 먼저 검사하는 이유도 같다 —
    "아니 괜찮아"처럼 두 표현이 같이 나오면 거절로 보는 편이 안전하다.
    """
    compact = _compact(text)
    if not compact:
        return None
    if any(_compact(pattern) in compact for pattern in _NO):
        return False
    if any(_compact(pattern) in compact for pattern in _YES):
        return True
    return None


def parse_choice(text: str, candidates: list[dict[str, Any]]) -> int | None:
    """여러 후보 중 어느 것을 고르셨는지 알아낸다. 못 알아들으면 None."""
    compact = _compact(text)
    if not compact or not candidates:
        return None

    for patterns, index in _ORDINALS:
        if index < len(candidates) and any(pattern in compact for pattern in patterns):
            return index

    names = [_compact(str(candidate.get("name") or "")) for candidate in candidates]

    # 이름을 통째로 말씀하신 경우.
    full = [index for index, name in enumerate(names) if name and name in compact]
    if len(full) == 1:
        return full[0]

    # 이름의 일부만 말씀하시는 편이 더 흔하다. "연세치과로 가자" -> "사당연세치과"
    # 긴 토막부터 보고, 한 곳만 가리킬 때에만 확정한다. "치과"처럼 여러 곳에
    # 해당하는 말은 고른 것으로 치면 안 되기 때문이다.
    for token in sorted(_name_tokens(text), key=len, reverse=True):
        hits = [index for index, name in enumerate(names) if name and token in name]
        if len(hits) == 1:
            return hits[0]
    return None


@dataclass
class Session:
    user_id: str
    awaiting: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    # 확정되면 그대로 /api/reservations로 보낼 요청 본문.
    pending_payload: dict[str, Any] = field(default_factory=dict)
    last_plan: dict[str, Any] = field(default_factory=dict)
    # 보호자에게 문자를 보내도 되는지. 예약이 확정되는 시점에는 분석 결과가 없으므로
    # 분석을 받은 턴에 기억해 둔다.
    guardian_notify_consent: str = "not_asked"
    updated_at: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def clear_pending(self) -> None:
        self.awaiting = ""
        self.candidates = []
        self.pending_payload = {}
        self.touch()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, user_id: str) -> Session:
        session = self._sessions.get(user_id)
        if session is None:
            session = Session(user_id=user_id)
            self._sessions[user_id] = session
        return session

    def reset(self, user_id: str) -> None:
        self._sessions.pop(user_id, None)
