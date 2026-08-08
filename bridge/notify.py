"""예약 확정 뒤 사용자·보호자에게 보낼 문자.

배차 서버가 조회 링크와 문구(`tracking_message`)를 만들어 주므로, 브릿지는
누구에게 보낼지 정하고 실제 발송기에 넘긴다.

**실제 문자 발송 게이트웨이는 아직 붙어 있지 않다.** 계약(SmsSender)과 기록용
구현만 두었고, 문자 사업자 연동은 별도 작업이다. 그래서 지금은 보낼 내용이
무엇인지 눈으로 확인하고 로그로 남기는 데까지만 한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

ROLE_ELDER = "elder"
ROLE_GUARDIAN = "guardian"


@dataclass(frozen=True, slots=True)
class SmsMessage:
    role: str  # elder | guardian
    to: str
    text: str


class SmsSender(Protocol):
    def send(self, message: SmsMessage) -> bool: ...


class RecordingSmsSender:
    """발송하지 않고 기록만 한다. 실제 게이트웨이가 붙기 전까지의 자리표시자.

    문자 내용에는 어르신의 목적지와 조회 링크가 들어가므로, 로그 파일은
    저장소에 커밋하지 않는다(.gitignore).
    """

    def __init__(self, log_path: str | Path | None = None, echo: bool = False) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.echo = echo
        self.sent: list[SmsMessage] = []

    def send(self, message: SmsMessage) -> bool:
        self.sent.append(message)
        if self.echo:
            print(f"[문자:{message.role}] -> {message.to}")
            for line in message.text.splitlines():
                print(f"    {line}")
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": message.role,
                    "to": message.to,
                    "text": message.text,
                    "delivered": False,  # 실제 발송이 아님을 명시한다
                }
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                return False
        return True


def build_messages(
    reservation: dict[str, Any],
    plan: dict[str, Any],
    *,
    elder_name: str = "",
    elder_contact: str = "",
    guardian_contact: str = "",
    guardian_notify_consent: str = "not_asked",
) -> list[SmsMessage]:
    """예약 결과로 보낼 문자 목록을 만든다.

    보호자 문자는 **동의가 확인된 경우에만** 만든다. 어르신의 이동 정보는
    본인 것이므로, 동의 없이 가족에게 알리지 않는다.
    """
    tracking_message = str(reservation.get("tracking_message") or "").strip()
    tracking_url = str(reservation.get("tracking_url") or "").strip()
    if not tracking_message and not tracking_url:
        # 배차 서버를 쓰지 않는 MOCK 모드에서는 보낼 링크가 없다.
        return []

    messages: list[SmsMessage] = []
    if elder_contact:
        messages.append(SmsMessage(ROLE_ELDER, elder_contact, tracking_message))

    if guardian_contact and guardian_notify_consent == "confirmed":
        messages.append(
            SmsMessage(ROLE_GUARDIAN, guardian_contact, _guardian_text(
                reservation, plan, elder_name, tracking_url,
            ))
        )
    return messages


def _guardian_text(
    reservation: dict[str, Any],
    plan: dict[str, Any],
    elder_name: str,
    tracking_url: str,
) -> str:
    boarding = (plan.get("boarding") or {}).get("name", "")
    destination = (plan.get("destination") or {}).get("name", "목적지")
    호칭 = f"{elder_name} 어르신" if elder_name else "어르신"

    lines = [f"{호칭}의 이동 차량이 예약되었습니다."]
    if boarding:
        lines.append(f"승차 장소: {boarding}")
    lines.append(f"목적지: {destination}")

    eta_s = reservation.get("estimated_arrival_s")
    if isinstance(eta_s, (int, float)) and eta_s > 0:
        lines.append(f"차량 도착까지 약 {max(1, round(eta_s / 60))}분")
    if tracking_url:
        lines.append(f"실시간 위치: {tracking_url}")
    return "\n".join(lines)
