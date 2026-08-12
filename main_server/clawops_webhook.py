"""ClawOps 통화 상태 웹훅 — call_id로 실제 통화 상대 번호를 미리 받아 둔다.

**배경**: ClawOps는 발신(outbound) 통화를 걸 때 상대방 번호를 이미 알고 있다.
예약 확정 문자를 그 번호로 보내려면 이 정보가 우리 시스템으로 전달돼야 하는데,
AI 에이전트가 음성으로 전화번호를 옮겨 적게 하면(전사 오류·환각 위험) 엉뚱한
번호로 문자가 샐 수 있다. 대신 ClawOps의 상태 콜백(status_callback) 웹훅으로
서버 대 서버 통신을 받고, `call_id`(에이전트가 시스템 컨텍스트에서 그대로
전달하는 불투명 식별자일 뿐 음성 전사 대상이 아니다)로 짝짓는다.

**2026-08-12 시점 주의**: ClawOps 웹훅의 정확한 필드명(특히 전화번호·통화ID
키 이름)을 공식 문서에서 확인하지 못했다(문서 사이트가 JS 렌더링이라 못 읽음).
`clawops` 파이썬 SDK가 Twilio류 서명 방식(HMAC-SHA256, URL+정렬된 폼 파라미터)을
쓰는 것으로 봐서 웹훅 바디도 Twilio류 관례(PascalCase 폼 인코딩: `CallSid`,
`To`, `CallStatus` 등)를 따를 가능성이 높다고 보고 후보 필드명 여러 개를
시도하도록 만들었다. `extract_call_id_and_phone()`이 실제 페이로드로 계속
실패하면, 처음 몇 번은 `print`로 원본 키를 그대로 남기니 Render 로그에서 실제
필드명을 확인해 이 목록을 정리해야 한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from urllib.parse import parse_qsl

_TTL_SECONDS = 600.0  # 웹훅이 통화 시작보다 먼저 도착해 대기하는 최대 시간(10분)


@dataclass(frozen=True, slots=True)
class _Entry:
    phone: str
    stored_at: float


class PendingCallRegistry:
    """call_id -> 통화 상대 전화번호. `start_call`이 claim할 때까지만 들고 있는다.

    스레드 세이프하게 만들어 둔다 — uvicorn이 여러 워커로 뜨면 위험하지만(그
    경우는 공유 저장소로 바꿔야 한다), 최소한 단일 프로세스 내 동시 요청은
    안전하게 처리한다.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = Lock()

    def store(self, call_id: str, phone: str) -> None:
        if not call_id or not phone:
            return
        with self._lock:
            self._entries[call_id] = _Entry(phone, time.monotonic())
            self._purge_expired_locked()

    def claim(self, call_id: str) -> str | None:
        """call_id로 번호를 찾아 돌려주고 저장소에서 지운다(한 번만 쓰인다).

        같은 call_id로 통화 상태 웹훅이 여러 번(ringing, in-progress, ...) 올 수
        있어 store()가 값을 여러 번 덮어쓸 수 있지만, claim은 start_call 시점에
        딱 한 번만 부르므로 문제 없다.
        """
        if not call_id:
            return None
        with self._lock:
            self._purge_expired_locked()
            entry = self._entries.pop(call_id, None)
        return entry.phone if entry else None

    def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [cid for cid, entry in self._entries.items() if now - entry.stored_at > _TTL_SECONDS]
        for cid in expired:
            del self._entries[cid]


def parse_payload(content_type: str, raw_body: bytes) -> dict[str, str]:
    """form-urlencoded 또는 JSON 어느 쪽으로 와도 dict[str, str]로 통일한다."""
    text = raw_body.decode("utf-8", errors="replace")
    if "application/json" in content_type:
        import json

        data = json.loads(text) if text.strip() else {}
        return {str(key): str(value) for key, value in data.items() if value is not None}
    # 기본값은 form-urlencoded로 본다 — Twilio류 통화 상태 콜백의 일반적인 형식이다.
    return dict(parse_qsl(text, keep_blank_values=True))


def extract_call_id_and_phone(fields: dict[str, str]) -> tuple[str, str, str]:
    """정확한 필드명을 아직 몰라 흔한 후보들을 순서대로 시도한다.

    반환: (call_id, phone, status). 못 찾으면 빈 문자열.
    """

    def pick(*names: str) -> str:
        for name in names:
            value = fields.get(name)
            if value:
                return value
        return ""

    call_id = pick("call_id", "CallSid", "CallId", "callId", "id")
    phone = pick("to", "To", "phone", "PhoneNumber", "caller", "Caller")
    status = pick("status", "CallStatus", "Status", "event", "Event")
    return call_id, phone, status
