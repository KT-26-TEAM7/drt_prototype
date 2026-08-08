from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Call, CallStatus, Stop, Vehicle, VehicleStatus
from app.schemas import CallCreateRequest, CallCreateResponse, CallStatusResponse
from app.services.call_state import synchronize_vehicle_states
from app.services.dispatch import find_nearest_available_vehicle
from app.services.routing import get_driving_route, serialize_route
from app.services.tracking_token import create_tracking_link
from app.services.tracking_notification import build_tracking_notification


router = APIRouter(tags=["calls"])


@router.post(
    "/calls",
    response_model=CallCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "출발 정류장과 도착 정류장이 동일함",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "출발 또는 도착 정류장을 찾을 수 없음",
        },
        status.HTTP_409_CONFLICT: {
            "description": "현재 이용 가능한 차량이 없음",
        },
    },
)
def create_call(
    request: CallCreateRequest,
    db: Session = Depends(get_db),
):
    if request.departure_stop_id == request.arrival_stop_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="출발 정류장과 도착 정류장은 달라야 합니다.",
        )

    departure_stop = db.get(Stop, request.departure_stop_id)
    if departure_stop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="출발 정류장을 찾을 수 없습니다.",
        )

    arrival_stop = db.get(Stop, request.arrival_stop_id)
    if arrival_stop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="도착 정류장을 찾을 수 없습니다.",
        )

    synchronize_vehicle_states(db)

    nearest_result = find_nearest_available_vehicle(db, departure_stop)
    if nearest_result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="현재 이용 가능한 차량이 없습니다.",
        )

    vehicle, approach_route, approach_travel_seconds = nearest_result
    call_id = f"CALL-{uuid4().hex[:8].upper()}"
    approach_start_latitude = vehicle.latitude
    approach_start_longitude = vehicle.longitude
    service_route = get_driving_route(
        departure_stop.latitude,
        departure_stop.longitude,
        arrival_stop.latitude,
        arrival_stop.longitude,
    )
    call = Call(
        id=call_id,
        vehicle_id=vehicle.id,
        departure_stop_id=departure_stop.id,
        arrival_stop_id=arrival_stop.id,
        status=CallStatus.DISPATCHED.value,
        estimated_arrival_seconds=approach_travel_seconds,
        approach_start_latitude=approach_start_latitude,
        approach_start_longitude=approach_start_longitude,
        approach_travel_seconds=approach_travel_seconds,
        stop_to_stop_travel_seconds=request.stop_to_stop_travel_seconds,
        approach_route_coordinates=serialize_route(approach_route),
        approach_route_source=approach_route.source,
        service_route_coordinates=serialize_route(service_route),
        service_route_source=service_route.source,
    )

    vehicle.status = VehicleStatus.DISPATCHED.value
    vehicle.current_call_id = call_id
    vehicle.roaming_start_latitude = None
    vehicle.roaming_start_longitude = None
    vehicle.roaming_end_latitude = None
    vehicle.roaming_end_longitude = None
    vehicle.roaming_started_at = None
    vehicle.roaming_arrival_at = None
    vehicle.roaming_route_coordinates = None
    vehicle.roaming_route_source = None

    db.add(call)
    tracking_link = create_tracking_link(db, call.id)
    tracking_notification = build_tracking_notification(
        tracking_link.url,
        departure_stop.name,
    )
    db.commit()
    db.refresh(call)
    db.refresh(vehicle)

    return CallCreateResponse(
        call_id=call.id,
        vehicle_id=vehicle.id,
        call_status=call.status,
        estimated_arrival_seconds=call.estimated_arrival_seconds,
        approach_travel_seconds=call.approach_travel_seconds,
        stop_to_stop_travel_seconds=call.stop_to_stop_travel_seconds,
        vehicle_latitude=vehicle.latitude,
        vehicle_longitude=vehicle.longitude,
        nearest_stop_id=vehicle.nearest_stop_id,
        tracking_url=tracking_link.url,
        tracking_message=tracking_notification.message,
    )


@router.get(
    "/calls/{call_id}",
    response_model=CallStatusResponse,
)
def get_call_status(
    call_id: str,
    db: Session = Depends(get_db),
):
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="호출 정보를 찾을 수 없습니다.",
        )

    vehicle = db.get(Vehicle, call.vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="배차된 차량 정보를 찾을 수 없습니다.",
        )

    vehicle_latitude = vehicle.latitude
    vehicle_longitude = vehicle.longitude
    nearest_stop_id = vehicle.nearest_stop_id
    if call.status == CallStatus.COMPLETED.value:
        arrival_stop = db.get(Stop, call.arrival_stop_id)
        if arrival_stop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="도착 정류장 정보를 찾을 수 없습니다.",
            )
        vehicle_latitude = arrival_stop.latitude
        vehicle_longitude = arrival_stop.longitude
        nearest_stop_id = arrival_stop.id

    return CallStatusResponse(
        call_id=call.id,
        vehicle_id=vehicle.id,
        departure_stop_id=call.departure_stop_id,
        arrival_stop_id=call.arrival_stop_id,
        call_status=call.status,
        estimated_arrival_seconds=call.estimated_arrival_seconds,
        approach_travel_seconds=call.approach_travel_seconds,
        stop_to_stop_travel_seconds=call.stop_to_stop_travel_seconds,
        vehicle_latitude=vehicle_latitude,
        vehicle_longitude=vehicle_longitude,
        nearest_stop_id=nearest_stop_id,
        updated_at=call.updated_at,
    )
