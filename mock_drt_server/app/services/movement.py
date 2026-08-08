from datetime import datetime
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import VEHICLE_SPEED_KMH
from app.db.models import Stop
from app.utils.geo import calculate_distance_km
from app.utils.geo import interpolate_position


def calculate_eta_seconds(distance_km: float) -> int:
    travel_hours = distance_km / VEHICLE_SPEED_KMH
    travel_seconds = int(travel_hours * 3600)
    return max(travel_seconds, 1)


def get_approach_travel_seconds(
    start_latitude: float,
    start_longitude: float,
    departure_stop: Stop,
) -> int:
    distance_km = calculate_distance_km(
        start_latitude,
        start_longitude,
        departure_stop.latitude,
        departure_stop.longitude,
    )
    return calculate_eta_seconds(distance_km)


def calculate_progress(
    current_time: datetime,
    started_at: datetime,
    arrival_at: datetime,
) -> float:
    total_seconds = (arrival_at - started_at).total_seconds()
    if total_seconds <= 0:
        return 1.0

    elapsed_seconds = (current_time - started_at).total_seconds()
    return max(0.0, min(elapsed_seconds / total_seconds, 1.0))


def calculate_remaining_seconds(
    current_time: datetime,
    arrival_at: datetime,
) -> int:
    return max(0, ceil((arrival_at - current_time).total_seconds()))


def find_nearest_stop(
    db: Session,
    latitude: float,
    longitude: float,
) -> Stop:
    stops = db.scalars(select(Stop)).all()
    if not stops:
        raise RuntimeError("등록된 정류장이 없습니다.")

    return min(
        stops,
        key=lambda stop: calculate_distance_km(
            latitude,
            longitude,
            stop.latitude,
            stop.longitude,
        ),
    )


def interpolate_route_position(
    coordinates: tuple[tuple[float, float], ...],
    progress: float,
) -> tuple[float, float]:
    if not coordinates:
        raise ValueError("경로 좌표가 없습니다.")
    if len(coordinates) == 1 or progress <= 0:
        return coordinates[0]
    if progress >= 1:
        return coordinates[-1]

    segment_distances = [
        calculate_distance_km(*start, *end) * 1000
        for start, end in zip(coordinates, coordinates[1:])
    ]
    total_distance = sum(segment_distances)
    if total_distance <= 0:
        return coordinates[-1]

    target_distance = total_distance * progress
    traversed_distance = 0.0
    for index, segment_distance in enumerate(segment_distances):
        next_distance = traversed_distance + segment_distance
        if target_distance <= next_distance:
            segment_progress = (
                (target_distance - traversed_distance) / segment_distance
                if segment_distance > 0
                else 1.0
            )
            start = coordinates[index]
            end = coordinates[index + 1]
            return (
                interpolate_position(start[0], end[0], segment_progress),
                interpolate_position(start[1], end[1], segment_progress),
            )
        traversed_distance = next_distance
    return coordinates[-1]
