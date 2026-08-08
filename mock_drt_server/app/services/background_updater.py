import logging
from threading import Event, Thread

from app.core.config import BACKGROUND_UPDATE_INTERVAL_SECONDS
from app.db.database import SessionLocal
from app.services.call_state import synchronize_vehicle_states


logger = logging.getLogger(__name__)


def run_vehicle_state_updater(stop_event: Event) -> None:
    while not stop_event.is_set():
        with SessionLocal() as db:
            try:
                synchronize_vehicle_states(db)
            except Exception:
                db.rollback()
                logger.exception("차량 상태 백그라운드 갱신에 실패했습니다.")

        stop_event.wait(BACKGROUND_UPDATE_INTERVAL_SECONDS)


def start_background_updater() -> tuple[Event, Thread]:
    stop_event = Event()
    updater_thread = Thread(
        target=run_vehicle_state_updater,
        args=(stop_event,),
        daemon=True,
    )
    updater_thread.start()
    return stop_event, updater_thread


def stop_background_updater(stop_event: Event, updater_thread: Thread) -> None:
    stop_event.set()
    updater_thread.join(timeout=BACKGROUND_UPDATE_INTERVAL_SECONDS + 1)
