from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import TRACKING_BASE_URL, TRACKING_TOKEN_TTL_HOURS
from app.db.models import TrackingToken


@dataclass(frozen=True, slots=True)
class CreatedTrackingLink:
    url: str
    raw_token: str
    expires_at: datetime


def hash_tracking_token(raw_token: str) -> str:
    return sha256(raw_token.encode("utf-8")).hexdigest()


def build_tracking_url(raw_token: str) -> str:
    """토큰을 경로가 아니라 쿼리스트링으로 붙인다.

    조회 화면(mock_drt_server/web/tracking, drt-tracking-main 기반)이 토큰을
    `?token=`으로 읽으므로, 링크 형식을 여기서 맞춘다.
    """
    scheme, netloc, path, query, fragment = urlsplit(TRACKING_BASE_URL)
    query_params = dict(parse_qsl(query, keep_blank_values=True))
    query_params["token"] = raw_token
    return urlunsplit((scheme, netloc, path, urlencode(query_params), fragment))


def create_tracking_link(
    db: Session,
    call_id: str,
    current_time: datetime | None = None,
) -> CreatedTrackingLink:
    existing_token = db.scalar(
        select(TrackingToken).where(TrackingToken.call_id == call_id)
    )
    if existing_token is not None:
        raise ValueError("이미 공개 조회 링크가 생성된 호출입니다.")

    now = current_time or datetime.now()
    raw_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=TRACKING_TOKEN_TTL_HOURS)
    db.add(
        TrackingToken(
            id=f"TRACK-{uuid4().hex.upper()}",
            call_id=call_id,
            token_hash=hash_tracking_token(raw_token),
            expires_at=expires_at,
            revoked_at=None,
            created_at=now,
        )
    )
    return CreatedTrackingLink(
        url=build_tracking_url(raw_token),
        raw_token=raw_token,
        expires_at=expires_at,
    )


def revoke_tracking_link(
    db: Session,
    call_id: str,
    current_time: datetime | None = None,
) -> None:
    tracking_token = db.scalar(
        select(TrackingToken).where(TrackingToken.call_id == call_id)
    )
    if tracking_token is None:
        raise ValueError("공개 조회 링크를 찾을 수 없습니다.")
    if tracking_token.revoked_at is None:
        tracking_token.revoked_at = current_time or datetime.now()
