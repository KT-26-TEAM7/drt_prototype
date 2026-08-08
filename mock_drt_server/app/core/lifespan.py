import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import tracking_base_url_warning
from app.db.database import SessionLocal
from app.db.seed import initialize_stops, initialize_vehicles
from app.services.call_state import synchronize_vehicle_states
from app.services.background_updater import (
    start_background_updater,
    stop_background_updater,
)

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 조회 링크 주소가 리슨 포트와 어긋나면 여기서 알린다. 그러지 않으면 사용자가
    # 문자를 눌러 봐야 알 수 있다.
    warning = tracking_base_url_warning()
    if warning:
        logger.warning("설정 확인 필요: %s", warning)

    with SessionLocal() as db:
        initialize_stops(db)
        initialize_vehicles(db)
        synchronize_vehicle_states(db)

    stop_event, updater_thread = start_background_updater()
    try:
        yield
    finally:
        stop_background_updater(stop_event, updater_thread)
