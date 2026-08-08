from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, StringConstraints


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CallStatusValue = Literal[
    "DISPATCHED",
    "APPROACHING",
    "ARRIVED",
    "IN_SERVICE",
    "COMPLETED",
]


class CallCreateRequest(BaseModel):
    departure_stop_id: NonEmptyString
    arrival_stop_id: NonEmptyString
    stop_to_stop_travel_seconds: int = Field(ge=1, le=7200)


class CallCreateResponse(BaseModel):
    call_id: NonEmptyString
    vehicle_id: NonEmptyString
    call_status: CallStatusValue
    estimated_arrival_seconds: int = Field(ge=0)
    approach_travel_seconds: int = Field(ge=1)
    stop_to_stop_travel_seconds: int = Field(ge=1, le=7200)
    vehicle_latitude: float = Field(ge=-90, le=90)
    vehicle_longitude: float = Field(ge=-180, le=180)
    nearest_stop_id: NonEmptyString
    tracking_url: AnyHttpUrl
    tracking_message: NonEmptyString


class CallStatusResponse(BaseModel):
    call_id: NonEmptyString
    vehicle_id: NonEmptyString
    departure_stop_id: NonEmptyString
    arrival_stop_id: NonEmptyString
    call_status: CallStatusValue
    estimated_arrival_seconds: int = Field(ge=0)
    approach_travel_seconds: int | None = Field(ge=1)
    stop_to_stop_travel_seconds: int | None = Field(ge=1, le=7200)
    vehicle_latitude: float = Field(ge=-90, le=90)
    vehicle_longitude: float = Field(ge=-180, le=180)
    nearest_stop_id: NonEmptyString
    updated_at: datetime
