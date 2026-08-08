from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.drt_client import DrtClient
from app.clients.tmap_client import POI, Coordinate, MockTmapClient, TmapClient, TmapError, poi_to_dict
from app.config import Settings
from app.db.session import get_db
from app.db.session import get_latest_location, get_station_by_id, import_stations as import_stations_db
from app.db.session import load_active_stations, save_location_ping
from app.db.session import save_reservation as save_reservation_db
from app.destination.confirm_destination import DestinationConfirmationError, confirm_destination
from app.destination.search_by_category import search_by_category
from app.destination.search_by_name import search_by_name
from app.reservation.confirm_reservation import confirm_reservation
from app.reservation.plan_route import (
    plan_category,
    plan_route,
    plan_specific,
    serialize_result,
    vehicle_route,
)
from app.schemas import (
    ArrivalStationRequest,
    ArrivalStationResponse,
    CategorySearchResponse,
    DepartureStationRequest,
    DepartureStationResponse,
    DestinationCandidatePayload,
    DestinationConfirmRequest,
    DestinationConfirmResponse,
    DestinationSearchRequest,
    DrtTravelTimeRequest,
    DrtTravelTimeResponse,
    LocationRequest,
    LocationResponse,
    NameSearchResponse,
    PlanRequest,
    PlanResponse,
    WalkLimitRequest,
    validate_location_quality,
)
from app.stations.find_arrival_station import find_arrival_station
from app.stations.find_departure_station import find_departure_station
from app.travel_time.estimate_duration import ETAContext, ETAService

router = APIRouter()

_KST = timezone(timedelta(hours=9))
_WEEKDAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _current_weekday_and_hour_kst() -> tuple[str, int]:
    now = datetime.now(_KST)
    return _WEEKDAY_CODES[now.weekday()], now.hour


def _build_eta_context(payload: PlanRequest) -> ETAContext:
    """요청의 weather/speed_level(선택)과 요청 시각(KST) 기준 weekday/hour로 ETA 조건을 만든다."""
    weekday, hour = _current_weekday_and_hour_kst()
    return ETAContext(
        weather=payload.weather or "clear",
        weekday=weekday,
        speed_level=payload.speed_level,
        hour=hour,
    )


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_tmap_client(request: Request) -> TmapClient | MockTmapClient:
    return request.app.state.tmap_client


def get_drt_client(request: Request) -> DrtClient:
    return request.app.state.drt_client


def get_eta_service(request: Request) -> ETAService:
    return request.app.state.eta_service


# 보안 스킴으로 등록해야 Swagger UI에 전역 Authorize 잠금이 뜬다.
# auto_error=False: 헤더가 없어도 여기서 422가 아니라 아래에서 401을 던지도록 함.
_relay_token_header = APIKeyHeader(name="X-Relay-Token", auto_error=False)


async def require_relay_token(
    settings: Settings = Depends(get_settings),
    x_relay_token: str | None = Security(_relay_token_header),
) -> None:
    if settings.relay_api_token and x_relay_token != settings.relay_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 릴레이 토큰입니다.")


def _validated_location(payload: LocationRequest, settings: Settings) -> dict:
    try:
        return validate_location_quality(
            payload,
            max_accuracy_m=settings.max_location_accuracy_m,
            max_age_s=settings.max_location_age_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def _walk_limit_m(payload: WalkLimitRequest, settings: Settings) -> float:
    """요청이 max_walk_m을 생략하면 서버 기본값을 적용한다."""
    return payload.max_walk_m if payload.max_walk_m is not None else settings.default_max_walk_m


def _serialize_poi(poi: POI) -> DestinationCandidatePayload:
    """plan_route.py::serialize_result가 destination에 쓰는 것과 같은 poi_to_dict를
    재사용해, 어느 API로 후보를 받든 필드 구성이 같도록 한다."""
    return DestinationCandidatePayload(**poi_to_dict(poi))


async def _require_station(db: AsyncSession, station_id: int, label: str):
    station = await get_station_by_id(db, station_id)
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} 정류장을 찾을 수 없습니다: {station_id}",
        )
    return station


@router.get("/", tags=["system"])
async def root(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "provider": "tmap" if settings.use_real_api else "mock",
        "dispatch": "drt_server" if settings.drt_server_base_url else "mock",
        "docs": "/docs",
    }


@router.get("/health", tags=["system"])
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    stations = await load_active_stations(db)
    return {"status": "ok", "database": "sqlite", "active_stations": len(stations)}


@router.post(
    "/api/location",
    response_model=LocationResponse,
    tags=["location"],
    dependencies=[Depends(require_relay_token)],
)
async def receive_location(
    payload: LocationRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> LocationResponse:
    _validated_location(payload, settings)
    location_id = await save_location_ping(
        db, payload.latitude, payload.longitude, payload.accuracy, payload.captured_at_iso()
    )
    return LocationResponse(
        ok=True,
        id=location_id,
        location=payload.model_dump(mode="json"),
    )


@router.get(
    "/api/location",
    response_model=LocationResponse,
    tags=["location"],
    dependencies=[Depends(require_relay_token)],
)
@router.get(
    "/api/location/latest",
    response_model=LocationResponse,
    include_in_schema=False,
    dependencies=[Depends(require_relay_token)],
)
async def latest_location(db: AsyncSession = Depends(get_db)) -> LocationResponse:
    location = await get_latest_location(db)
    return LocationResponse(ok=location is not None, location=location)


@router.post(
    "/api/reverse-geocode",
    tags=["location"],
    dependencies=[Depends(require_relay_token)],
)
async def reverse_geocode(
    payload: LocationRequest,
    settings: Settings = Depends(get_settings),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
) -> dict:
    _validated_location(payload, settings)
    try:
        result = await tmap_client.reverse_geocode(payload.latitude, payload.longitude)
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {
        "ok": result.get("ok", False),
        "provider": "tmap" if settings.use_real_api else "mock",
        "address": result,
    }


@router.post(
    "/api/stations/departure",
    response_model=DepartureStationResponse,
    tags=["stations"],
    dependencies=[Depends(require_relay_token)],
)
async def departure_station(
    payload: DepartureStationRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
) -> DepartureStationResponse:
    _validated_location(payload, settings)
    await save_location_ping(
        db, payload.latitude, payload.longitude, payload.accuracy, payload.captured_at_iso()
    )
    stations = await load_active_stations(db)
    origin = Coordinate(payload.latitude, payload.longitude)
    max_walk_m = _walk_limit_m(payload, settings)
    try:
        result = await find_departure_station(
            origin, stations, tmap_client, max_walk_m, settings.shortlist_top_k
        )
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    result["applied_max_walk_m"] = max_walk_m
    return DepartureStationResponse(**serialize_result(result))


@router.post(
    "/api/stations/arrival",
    response_model=ArrivalStationResponse,
    tags=["stations"],
    dependencies=[Depends(require_relay_token)],
)
async def arrival_station(
    payload: ArrivalStationRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
) -> ArrivalStationResponse:
    stations = await load_active_stations(db)
    destination = Coordinate(payload.latitude, payload.longitude)
    max_walk_m = payload.max_walk_m if payload.max_walk_m is not None else settings.default_max_walk_m
    try:
        result = await find_arrival_station(
            destination, payload.destination_name, stations, tmap_client, max_walk_m, settings.shortlist_top_k
        )
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    result["applied_max_walk_m"] = max_walk_m
    return ArrivalStationResponse(**serialize_result(result))


@router.post(
    "/api/destinations/confirm",
    response_model=DestinationConfirmResponse,
    tags=["destination"],
    dependencies=[Depends(require_relay_token)],
)
async def confirm_destination_endpoint(payload: DestinationConfirmRequest) -> DestinationConfirmResponse:
    try:
        return confirm_destination(payload)
    except DestinationConfirmationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/api/destinations/category-search",
    response_model=CategorySearchResponse,
    tags=["destination"],
    dependencies=[Depends(require_relay_token)],
)
async def category_search_endpoint(
    payload: DestinationSearchRequest,
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
) -> CategorySearchResponse:
    """2단계(대분류/case1) 단독 확인용: 승차 정류장 기준 검색어 후보를 그대로 노출한다."""
    station = await _require_station(db, payload.boarding_station_id, "승차")
    try:
        result = await search_by_category(
            tmap_client, payload.query, Coordinate(station.lat, station.lon)
        )
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return CategorySearchResponse(
        status=result["status"],
        candidates=[_serialize_poi(poi) for poi in result["candidates"]],
        reason=result["reason"],
        used_radius_m=result.get("used_radius_m"),
        radius_expanded=result.get("radius_expanded"),
    )


@router.post(
    "/api/destinations/name-search",
    response_model=NameSearchResponse,
    tags=["destination"],
    dependencies=[Depends(require_relay_token)],
)
async def name_search_endpoint(
    payload: DestinationSearchRequest,
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
) -> NameSearchResponse:
    """2단계(정확명/case2) 단독 확인용: 승차 정류장 기준 정확명 검색 후보를 그대로 노출한다."""
    station = await _require_station(db, payload.boarding_station_id, "승차")
    result = await search_by_name(tmap_client, payload.query, Coordinate(station.lat, station.lon))
    return NameSearchResponse(
        status=result["status"],
        candidates=[_serialize_poi(poi) for poi in result["candidates"]],
        reason=result["reason"],
    )


@router.post(
    "/api/travel-time/drt",
    response_model=DrtTravelTimeResponse,
    tags=["travel-time"],
    dependencies=[Depends(require_relay_token)],
)
async def drt_travel_time_endpoint(
    payload: DrtTravelTimeRequest,
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
    eta_service: ETAService = Depends(get_eta_service),
) -> DrtTravelTimeResponse:
    """5~6단계 단독 확인용: 정류장 간 DRT 차량시간(ETA 모델, 실패 시 TMAP 폴백)을 계산하고,
    승·하차 도보시간을 함께 보내면 총 합산 시간도 계산한다."""
    boarding = await _require_station(db, payload.boarding_station_id, "승차")
    alighting = await _require_station(db, payload.alighting_station_id, "하차")
    weekday, hour = _current_weekday_and_hour_kst()
    context = ETAContext(
        weather=payload.weather or "clear",
        weekday=weekday,
        speed_level=payload.speed_level,
        hour=hour,
    )
    try:
        route = await vehicle_route(boarding, alighting, tmap_client, eta_service, context)
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    total: float | None = None
    if payload.boarding_walk_duration_s is not None and payload.alighting_walk_duration_s is not None:
        total = payload.boarding_walk_duration_s + route.duration_s + payload.alighting_walk_duration_s

    return DrtTravelTimeResponse(
        distance_m=round(route.distance_m),
        duration_s=round(route.duration_s),
        source=route.source,
        total_travel_time_s=total,
    )


@router.post(
    "/api/plan",
    response_model=PlanResponse,
    tags=["planning"],
    dependencies=[Depends(require_relay_token)],
)
async def create_plan(
    payload: PlanRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
    eta_service: ETAService = Depends(get_eta_service),
) -> PlanResponse:
    location_validation = _validated_location(payload, settings)
    await save_location_ping(
        db, payload.latitude, payload.longitude, payload.accuracy, payload.captured_at_iso()
    )
    stations = await load_active_stations(db)
    origin = Coordinate(payload.latitude, payload.longitude)
    max_walk_m = _walk_limit_m(payload, settings)
    eta_context = _build_eta_context(payload)
    try:
        origin_address = await tmap_client.reverse_geocode(payload.latitude, payload.longitude)
        planner = plan_specific if payload.is_specific else plan_category
        result = await planner(
            payload.query,
            origin,
            stations,
            tmap_client,
            eta_service,
            eta_context,
            max_walk_m,
            payload.expected_wait_s,
        )
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    result["applied_max_walk_m"] = max_walk_m
    result["applied_expected_wait_s"] = payload.expected_wait_s
    result["origin"] = {
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "accuracy": payload.accuracy,
        "captured_at": payload.captured_at_iso(),
    }
    result["origin_address"] = origin_address
    result["location_validation"] = location_validation
    return PlanResponse(ok=True, plan=serialize_result(result))


@router.post("/api/reservations", tags=["reservation"], dependencies=[Depends(require_relay_token)])
async def create_reservation(
    payload: PlanRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    tmap_client: TmapClient | MockTmapClient = Depends(get_tmap_client),
    drt_client: DrtClient = Depends(get_drt_client),
    eta_service: ETAService = Depends(get_eta_service),
) -> dict:
    location_validation = _validated_location(payload, settings)
    stations = await load_active_stations(db)
    origin = Coordinate(payload.latitude, payload.longitude)
    eta_context = _build_eta_context(payload)
    try:
        plan = await plan_route(
            payload.query,
            origin,
            stations,
            tmap_client,
            eta_service,
            eta_context,
            is_specific=payload.is_specific,
            max_walk_m=_walk_limit_m(payload, settings),
            expected_wait_s=payload.expected_wait_s,
        )
    except TmapError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    confirmation = await confirm_reservation(plan, drt_client)
    reservation = confirmation["reservation"]
    if reservation:
        await save_reservation_db(
            db,
            reservation["call_id"],
            reservation["status"],
            reservation["boarding_station_id"],
            reservation["alighting_station_id"],
            payload.expected_wait_s,
            reservation["requested_at"],
        )

    return {
        "ok": confirmation["ok"],
        "reason": confirmation["reason"],
        "plan": plan,
        "reservation": reservation,
        "location_validation": location_validation,
    }


@router.get("/api/stations", tags=["stations"], dependencies=[Depends(require_relay_token)])
async def list_stations(db: AsyncSession = Depends(get_db)) -> dict:
    stations = await load_active_stations(db)
    return {
        "count": len(stations),
        "stations": [
            {
                "station_id": station.station_id,
                "name": station.name,
                "station_type": station.station_type,
                "latitude": station.lat,
                "longitude": station.lon,
                "coverage_radius_m": station.coverage_radius_m,
                "walk_limit_m": station.walk_limit_m,
                "ext_id": station.ext_id,
            }
            for station in stations
        ],
    }


@router.post("/api/stations/import", tags=["stations"], dependencies=[Depends(require_relay_token)])
async def import_stations(
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> dict:
    count = await import_stations_db(db, settings.stations_csv_path)
    return {"ok": True, "imported": count}


@router.get("/api/sender", tags=["tools"], response_class=FileResponse)
async def location_sender(settings: Settings = Depends(get_settings)) -> FileResponse:
    html_path = settings.web_dir / "location_sender.html"
    if not html_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="위치 전송 페이지가 없습니다.")
    return FileResponse(html_path, media_type="text/html; charset=utf-8")
