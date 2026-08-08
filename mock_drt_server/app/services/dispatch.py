from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import VEHICLE_COUNT
from app.db.models import Stop, Vehicle, VehicleStatus
from app.services.movement import calculate_eta_seconds
from app.services.routing import RoutePath, get_driving_route


def find_nearest_available_vehicle(
    db: Session,
    departure_stop: Stop,
) -> tuple[Vehicle, RoutePath, int] | None:
    dispatchable_vehicle_ids = (
        select(Vehicle.id).order_by(Vehicle.id).limit(VEHICLE_COUNT)
    )
    vehicles = db.scalars(
        select(Vehicle).where(
            Vehicle.id.in_(dispatchable_vehicle_ids),
            Vehicle.status == VehicleStatus.AVAILABLE.value,
        )
    ).all()
    if not vehicles:
        return None

    route_arguments = [
        (
            vehicle.latitude,
            vehicle.longitude,
            departure_stop.latitude,
            departure_stop.longitude,
        )
        for vehicle in vehicles
    ]
    with ThreadPoolExecutor(max_workers=len(vehicles)) as executor:
        routes = executor.map(
            lambda arguments: get_driving_route(*arguments),
            route_arguments,
        )

    candidates: list[tuple[Vehicle, RoutePath, int]] = []
    for vehicle, route in zip(vehicles, routes):
        travel_seconds = route.duration_seconds or calculate_eta_seconds(
            route.distance_m / 1000
        )
        candidates.append((vehicle, route, travel_seconds))

    return min(candidates, key=lambda item: item[2])
