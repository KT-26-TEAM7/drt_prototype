from pydantic import BaseModel, Field


class StopResponse(BaseModel):
    stop_id: str
    stop_name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
