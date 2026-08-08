from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Vehicle
from app.schemas import VehicleResponse


router = APIRouter(tags=["vehicles"])


@router.get("/vehicles", response_model=list[VehicleResponse])
def get_vehicles(db: Session = Depends(get_db)):
    vehicles = db.scalars(select(Vehicle)).all()
    return [
        {
            "vehicle_id": vehicle.id,
            "latitude": vehicle.latitude,
            "longitude": vehicle.longitude,
            "nearest_stop_id": vehicle.nearest_stop_id,
            "status": vehicle.status,
            "current_call_id": vehicle.current_call_id,
        }
        for vehicle in vehicles
    ]
