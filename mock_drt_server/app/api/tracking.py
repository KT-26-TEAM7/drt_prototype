from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.db.database import get_db
from app.schemas.tracking import TrackingStatusResponse
from app.services.tracking import (
    TrackingNotFoundError,
    TrackingUnavailableError,
    get_tracking,
)


router = APIRouter(prefix="/tracking", tags=["tracking"])
TRACKING_HTML_PATH = PROJECT_ROOT / "web" / "tracking" / "index.html"
_TRACKING_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@router.get("", response_class=HTMLResponse)
def tracking_dashboard():
    """조회 화면(정적 페이지)을 서빙한다.

    토큰은 경로가 아니라 쿼리스트링(`?token=...`)으로 오므로 서버는 그것을 몰라도
    된다 — 화면 쪽 JS가 `window.location.search`에서 직접 읽어 `/status`를 조회한다.
    지도(Leaflet+OSM)는 TMAP 키 없이도 그려지므로 별도 주입도 필요 없다.
    """
    html = TRACKING_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html, headers=_TRACKING_HEADERS)


@router.get("/{token}", response_class=HTMLResponse)
def tracking_dashboard_legacy_link(token: str):
    """예전 경로형 링크(`/tracking/{token}`)를 새 쿼리형으로 되돌려 보낸다.

    링크 형식이 바뀌기 전에 이미 발송된 문자·`data/sent_sms.jsonl` 기록이 있을 수
    있으므로, 깨뜨리지 않고 새 화면으로 넘겨준다.
    """
    return RedirectResponse(f"/tracking?token={token}", status_code=307)


@router.get("/{token}/status", response_model=TrackingStatusResponse)
def get_tracking_status(
    token: str,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        return get_tracking(db, token)
    except TrackingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except TrackingUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=str(exc),
        ) from exc
