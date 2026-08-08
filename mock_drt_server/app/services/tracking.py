from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Call, Stop, TrackingToken, Vehicle
from app.schemas.tracking import (
    TrackingStatusResponse,
    TrackingRoute,
    TrackingStop,
    TrackingVehicle,
)
from app.services.tracking_token import hash_tracking_token
from app.services.routing import (
    deserialize_route,
    straight_route,
)


STATUS_MESSAGES = {
    "DISPATCHED": "차량이 배정되었습니다.",
    "APPROACHING": "차량이 승차 장소로 이동하고 있습니다.",
    "ARRIVED": "차량이 승차 장소에 도착했습니다.",
    "IN_SERVICE": "목적지로 이동하고 있습니다.",
    "COMPLETED": "운행이 완료되었습니다.",
}


class TrackingNotFoundError(ValueError):
    pass


class TrackingUnavailableError(ValueError):
    pass


def get_tracking(
    db: Session,
    raw_token: str,
    current_time: datetime | None = None,
) -> TrackingStatusResponse:
    now = current_time or datetime.now()
    tracking_token = db.scalar(
        select(TrackingToken).where(
            TrackingToken.token_hash == hash_tracking_token(raw_token)
        )
    )
    if tracking_token is None:
        raise TrackingNotFoundError("조회 링크를 찾을 수 없습니다.")
    if tracking_token.revoked_at is not None:
        raise TrackingUnavailableError("폐기된 조회 링크입니다.")
    if now >= tracking_token.expires_at:
        raise TrackingUnavailableError("만료된 조회 링크입니다.")

    call = db.get(Call, tracking_token.call_id)
    if call is None:
        raise TrackingNotFoundError("예약 정보를 찾을 수 없습니다.")
    vehicle = db.get(Vehicle, call.vehicle_id)
    departure_stop = db.get(Stop, call.departure_stop_id)
    arrival_stop = db.get(Stop, call.arrival_stop_id)
    if vehicle is None or departure_stop is None or arrival_stop is None:
        raise TrackingNotFoundError("운행 정보를 찾을 수 없습니다.")
    stops = db.scalars(select(Stop).order_by(Stop.id)).all()

    if call.status in {"DISPATCHED", "APPROACHING", "ARRIVED"}:
        route_coordinates = deserialize_route(call.approach_route_coordinates)
        route_source = call.approach_route_source or "straight_fallback"
        if not route_coordinates:
            route = straight_route(
                call.approach_start_latitude or vehicle.latitude,
                call.approach_start_longitude or vehicle.longitude,
                departure_stop.latitude,
                departure_stop.longitude,
            )
            route_coordinates = route.coordinates
            route_source = route.source
    else:
        route_coordinates = deserialize_route(call.service_route_coordinates)
        route_source = call.service_route_source or "straight_fallback"
        if not route_coordinates:
            route = straight_route(
                departure_stop.latitude,
                departure_stop.longitude,
                arrival_stop.latitude,
                arrival_stop.longitude,
            )
            route_coordinates = route.coordinates
            route_source = route.source

    return TrackingStatusResponse(
        status=call.status,
        status_message=STATUS_MESSAGES[call.status],
        vehicle=TrackingVehicle(
            display_name=_vehicle_display_name(vehicle.id),
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
        ),
        departure_stop=TrackingStop(
            name=departure_stop.name,
            latitude=departure_stop.latitude,
            longitude=departure_stop.longitude,
        ),
        arrival_stop=TrackingStop(
            name=arrival_stop.name,
            latitude=arrival_stop.latitude,
            longitude=arrival_stop.longitude,
        ),
        stops=[
            TrackingStop(
                name=stop.name,
                latitude=stop.latitude,
                longitude=stop.longitude,
            )
            for stop in stops
        ],
        route=TrackingRoute(
            coordinates=list(route_coordinates),
            source=route_source,
        ),
        estimated_arrival_seconds=call.estimated_arrival_seconds,
        updated_at=call.updated_at,
    )


def _vehicle_display_name(vehicle_id: str) -> str:
    try:
        vehicle_number = int(vehicle_id.rsplit("-", 1)[-1])
    except ValueError:
        return "DRT 차량"
    return f"DRT {vehicle_number}호차"
