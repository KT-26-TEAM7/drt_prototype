from typing import Literal

from pydantic import BaseModel, Field


class VehicleResponse(BaseModel):
    vehicle_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    nearest_stop_id: str
    status: Literal["AVAILABLE", "DISPATCHED"]
    current_call_id: str | None
