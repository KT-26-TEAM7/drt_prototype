import random
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Stop, Vehicle
from app.services.movement import (
    calculate_eta_seconds,
    find_nearest_stop,
    interpolate_route_position,
)
from app.services.routing import (
    deserialize_route,
    get_driving_route,
    serialize_route,
)


def start_vehicle_roaming(
    db: Session,
    vehicle: Vehicle,
    started_at: datetime,
) -> None:
    candidate_stops = list(
        db.scalars(
            select(Stop).where(Stop.id != vehicle.nearest_stop_id)
        ).all()
    )
    if not candidate_stops:
        return

    target_stop = random.choice(candidate_stops)
    route = get_driving_route(
        vehicle.latitude,
        vehicle.longitude,
        target_stop.latitude,
        target_stop.longitude,
    )
    travel_seconds = route.duration_seconds or calculate_eta_seconds(
        route.distance_m / 1000
    )
    vehicle.roaming_start_latitude = vehicle.latitude
    vehicle.roaming_start_longitude = vehicle.longitude
    vehicle.roaming_end_latitude = target_stop.latitude
    vehicle.roaming_end_longitude = target_stop.longitude
    vehicle.roaming_started_at = started_at
    vehicle.roaming_arrival_at = started_at + timedelta(seconds=travel_seconds)
    vehicle.roaming_route_coordinates = serialize_route(route)
    vehicle.roaming_route_source = route.source


def synchronize_roaming_vehicle(
    db: Session,
    vehicle: Vehicle,
    current_time: datetime,
) -> None:
    if vehicle.roaming_started_at is None or vehicle.roaming_arrival_at is None:
        start_vehicle_roaming(db, vehicle, current_time)
        return

    coordinates = (
        vehicle.roaming_start_latitude,
        vehicle.roaming_start_longitude,
        vehicle.roaming_end_latitude,
        vehicle.roaming_end_longitude,
    )
    if any(value is None for value in coordinates):
        start_vehicle_roaming(db, vehicle, current_time)
        return

    segment_seconds = (
        vehicle.roaming_arrival_at - vehicle.roaming_started_at
    ).total_seconds()
    if segment_seconds <= 0:
        start_vehicle_roaming(db, vehicle, current_time)
        return

    elapsed_seconds = max(
        0.0,
        (current_time - vehicle.roaming_started_at).total_seconds(),
    )
    cycle_index = int(elapsed_seconds // segment_seconds)
    progress = (elapsed_seconds % segment_seconds) / segment_seconds
    if cycle_index % 2 == 1:
        progress = 1.0 - progress

    route_coordinates = deserialize_route(vehicle.roaming_route_coordinates)
    if not route_coordinates:
        route = get_driving_route(
            vehicle.roaming_start_latitude,
            vehicle.roaming_start_longitude,
            vehicle.roaming_end_latitude,
            vehicle.roaming_end_longitude,
        )
        vehicle.roaming_route_coordinates = serialize_route(route)
        vehicle.roaming_route_source = route.source
        route_coordinates = route.coordinates
    vehicle.latitude, vehicle.longitude = interpolate_route_position(
        route_coordinates,
        progress,
    )
    nearest_stop = find_nearest_stop(db, vehicle.latitude, vehicle.longitude)
    vehicle.nearest_stop_id = nearest_stop.id
