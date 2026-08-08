from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


PublicCallStatus = Literal[
    "DISPATCHED",
    "APPROACHING",
    "ARRIVED",
    "IN_SERVICE",
    "COMPLETED",
]


class TrackingVehicle(BaseModel):
    display_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TrackingStop(BaseModel):
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TrackingRoute(BaseModel):
    coordinates: list[tuple[float, float]]
    source: Literal["tmap", "straight_fallback"]


class TrackingStatusResponse(BaseModel):
    status: PublicCallStatus
    status_message: str
    vehicle: TrackingVehicle
    departure_stop: TrackingStop
    arrival_stop: TrackingStop
    stops: list[TrackingStop]
    route: TrackingRoute
    estimated_arrival_seconds: int = Field(ge=0)
    updated_at: datetime
