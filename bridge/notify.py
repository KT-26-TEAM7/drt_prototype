"""예약 확정 뒤 사용자·보호자에게 보낼 문자.

배차 서버가 조회 링크와 문구(`tracking_message`)를 만들어 주므로, 브릿지는
누구에게 보낼지 정하고 실제 발송기에 넘긴다.

**2026-08-12부터 ClawOps 메시지 API로 실제 발송이 가능하다**(`ClawOpsSmsSender`,
전화 연동에 이미 쓰고 있는 ClawOps 계정을 그대로 쓴다). 키가 없거나
`clawops` 패키지가 안 깔려 있으면 `RecordingSmsSender`(기록만)로 자동 폴백한다.
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


class ClawOpsSmsSender:
    """ClawOps 메시지 API로 실제 문자를 보낸다.

    전화 연동에 이미 쓰고 있는 ClawOps 계정(API & Webhooks에서 발급한 API 키·
    Account ID)을 그대로 쓴다. 발신 번호는 그 계정에 **사전 등록된 번호**여야
    한다(ClawOps SDK `Messages.create`의 제약) — 통화에 쓰는 070 번호를 쓰면 된다.

    `clawops` 패키지는 선택 의존성이다(설치 안 돼 있으면 이 클래스를 쓰지 않고
    `RecordingSmsSender`로 대신한다 — `main_server/care_bridge.py` 참고).
    """

    def __init__(
        self,
        api_key: str,
        account_id: str,
        from_number: str,
        *,
        log_path: str | Path | None = None,
    ) -> None:
        import clawops  # 지연 import — 미설치 환경에서도 모듈 자체는 로드되게

        self._clawops = clawops
        self._client = clawops.ClawOps(api_key=api_key, account_id=account_id)
        self._from = from_number
        self.log_path = Path(log_path) if log_path else None
        self.sent: list[SmsMessage] = []

    def send(self, message: SmsMessage) -> bool:
        self.sent.append(message)
        error: str | None = None
        message_id: str | None = None
        try:
            result = self._client.messages.create(
                to=message.to, from_=self._from, body=message.text, type="sms",
            )
            # queued/sending/sent는 접수된 것으로 본다 — 실제 통신망 전달까지는
            # 비동기라 이 시점에 최종 배달 확인은 안 된다.
            ok = result.status in {"queued", "sending", "sent"}
            message_id = result.message_id
            if not ok:
                error = f"status={result.status}"
        except self._clawops.ClawOpsError as exc:
            ok = False
            error = f"{type(exc).__name__}: {exc}"

        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": message.role,
                    "to": message.to,
                    "text": message.text,
                    "delivered": ok,
                    "message_id": message_id,
                    "error": error,
                }
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return ok


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
