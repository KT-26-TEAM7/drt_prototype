from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ARRIVAL_WAIT_SECONDS
from app.db.models import Call, CallStatus, Stop, Vehicle, VehicleStatus
from app.services.movement import (
    calculate_progress,
    calculate_remaining_seconds,
    find_nearest_stop,
    interpolate_route_position,
)
from app.services.roaming import (
    start_vehicle_roaming,
    synchronize_roaming_vehicle,
)
from app.services.routing import (
    deserialize_route,
    get_driving_route,
    serialize_route,
)


def synchronize_call_state(
    db: Session,
    call: Call,
    current_time: datetime | None = None,
) -> Vehicle | None:
    vehicle = db.get(Vehicle, call.vehicle_id)
    departure_stop = db.get(Stop, call.departure_stop_id)
    arrival_stop = db.get(Stop, call.arrival_stop_id)
    if vehicle is None or departure_stop is None or arrival_stop is None:
        return vehicle

    now = current_time or datetime.now()
    approach_seconds = call.approach_travel_seconds or max(
        call.estimated_arrival_seconds,
        1,
    )
    service_seconds = call.stop_to_stop_travel_seconds or 1
    approach_started_at = call.created_at
    approach_arrival_at = approach_started_at + timedelta(seconds=approach_seconds)
    service_started_at = approach_arrival_at + timedelta(
        seconds=ARRIVAL_WAIT_SECONDS
    )
    service_arrival_at = service_started_at + timedelta(seconds=service_seconds)
    start_latitude = call.approach_start_latitude
    start_longitude = call.approach_start_longitude
    if start_latitude is None:
        start_latitude = vehicle.latitude
    if start_longitude is None:
        start_longitude = vehicle.longitude

    approach_route = deserialize_route(call.approach_route_coordinates)
    if not approach_route:
        route = get_driving_route(
            start_latitude,
            start_longitude,
            departure_stop.latitude,
            departure_stop.longitude,
        )
        call.approach_route_coordinates = serialize_route(route)
        call.approach_route_source = route.source
        approach_route = route.coordinates
    service_route = deserialize_route(call.service_route_coordinates)
    if not service_route:
        route = get_driving_route(
            departure_stop.latitude,
            departure_stop.longitude,
            arrival_stop.latitude,
            arrival_stop.longitude,
        )
        call.service_route_coordinates = serialize_route(route)
        call.service_route_source = route.source
        service_route = route.coordinates

    if now < approach_arrival_at:
        progress = calculate_progress(now, approach_started_at, approach_arrival_at)
        call.status = CallStatus.APPROACHING.value
        call.estimated_arrival_seconds = calculate_remaining_seconds(
            now, approach_arrival_at
        )
        vehicle.latitude, vehicle.longitude = interpolate_route_position(
            approach_route,
            progress,
        )
    elif now < service_started_at:
        call.status = CallStatus.ARRIVED.value
        call.estimated_arrival_seconds = 0
        vehicle.latitude = departure_stop.latitude
        vehicle.longitude = departure_stop.longitude
    elif now < service_arrival_at:
        progress = calculate_progress(now, service_started_at, service_arrival_at)
        call.status = CallStatus.IN_SERVICE.value
        call.estimated_arrival_seconds = calculate_remaining_seconds(
            now, service_arrival_at
        )
        vehicle.latitude, vehicle.longitude = interpolate_route_position(
            service_route,
            progress,
        )
    else:
        call.status = CallStatus.COMPLETED.value
        call.estimated_arrival_seconds = 0
        vehicle.latitude = arrival_stop.latitude
        vehicle.longitude = arrival_stop.longitude
        vehicle.status = VehicleStatus.AVAILABLE.value
        if vehicle.current_call_id == call.id:
            vehicle.current_call_id = None
            vehicle.nearest_stop_id = arrival_stop.id
            start_vehicle_roaming(db, vehicle, service_arrival_at)
            synchronize_roaming_vehicle(db, vehicle, now)

    nearest_stop = find_nearest_stop(db, vehicle.latitude, vehicle.longitude)
    vehicle.nearest_stop_id = nearest_stop.id
    return vehicle


def synchronize_vehicle_states(db: Session) -> None:
    active_calls = db.scalars(
        select(Call)
        .join(Vehicle, Vehicle.id == Call.vehicle_id)
        .where(
            Vehicle.current_call_id == Call.id,
            Vehicle.status == VehicleStatus.DISPATCHED.value,
        )
    ).all()
    current_time = datetime.now()
    for call in active_calls:
        synchronize_call_state(db, call, current_time)

    available_vehicles = db.scalars(
        select(Vehicle).where(Vehicle.status == VehicleStatus.AVAILABLE.value)
    ).all()
    for vehicle in available_vehicles:
        synchronize_roaming_vehicle(db, vehicle, current_time)

    db.commit()
