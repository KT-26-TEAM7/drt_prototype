import random
from csv import DictReader
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import STOPS_CSV_PATH, VEHICLE_COUNT
from app.db.models import Stop, Vehicle, VehicleStatus
from app.services.roaming import start_vehicle_roaming


@dataclass(frozen=True, slots=True)
class StopSeed:
    id: str
    name: str
    latitude: float
    longitude: float


def load_stops_from_csv() -> list[StopSeed]:
    with STOPS_CSV_PATH.open(encoding="utf-8-sig") as file:
        return [
            StopSeed(
                id=row["id"],
                name=row["name"],
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
            )
            for row in DictReader(file)
        ]


def initialize_stops(db: Session) -> None:
    existing_stop_ids = set(db.scalars(select(Stop.id)).all())
    missing_stops = [
        Stop(
            id=seed.id,
            name=seed.name,
            latitude=seed.latitude,
            longitude=seed.longitude,
        )
        for seed in load_stops_from_csv()
        if seed.id not in existing_stop_ids
    ]
    if missing_stops:
        db.add_all(missing_stops)
        db.commit()


def initialize_vehicles(db: Session) -> None:
    existing_vehicle_ids = set(db.scalars(select(Vehicle.id)).all())
    missing_vehicle_ids = [
        f"VEHICLE-{index:03d}"
        for index in range(1, VEHICLE_COUNT + 1)
        if f"VEHICLE-{index:03d}" not in existing_vehicle_ids
    ]
    if not missing_vehicle_ids:
        return

    stops = list(db.scalars(select(Stop)).all())
    if not stops:
        raise RuntimeError("차량을 배치할 정류장이 없습니다.")

    started_at = datetime.now()
    for vehicle_id, stop in zip(
        missing_vehicle_ids,
        random.choices(stops, k=len(missing_vehicle_ids)),
    ):
        vehicle = Vehicle(
            id=vehicle_id,
            latitude=stop.latitude,
            longitude=stop.longitude,
            nearest_stop_id=stop.id,
            status=VehicleStatus.AVAILABLE.value,
            current_call_id=None,
        )
        db.add(vehicle)
        start_vehicle_roaming(db, vehicle, started_at)
    db.commit()
