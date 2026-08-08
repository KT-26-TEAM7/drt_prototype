from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Stop
from app.schemas import StopResponse


router = APIRouter(tags=["stops"])


@router.get("/stops", response_model=list[StopResponse])
def get_stops(db: Session = Depends(get_db)):
    stops = db.scalars(select(Stop)).all()
    return [
        StopResponse(
            stop_id=stop.id,
            stop_name=stop.name,
            latitude=stop.latitude,
            longitude=stop.longitude
        )
        for stop in stops
    ]
