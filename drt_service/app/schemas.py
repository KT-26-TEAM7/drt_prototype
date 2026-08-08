from __future__ import annotations

import math
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90, examples=[37.4849])
    longitude: float = Field(ge=-180, le=180, examples=[126.9710])
    accuracy: float | None = Field(default=None, ge=0, examples=[12.5])
    captured_at: datetime | None = None

    @field_validator("latitude", "longitude", "accuracy")
    @classmethod
    def finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("유한한 숫자여야 합니다.")
        return value

    def captured_at_iso(self) -> str | None:
        return self.captured_at.isoformat() if self.captured_at else None


class WalkLimitRequest(LocationRequest):
    """max_walk_m을 생략하면 서버 설정(Settings.default_max_walk_m)을 적용한다."""

    max_walk_m: float | None = Field(default=None, gt=0, le=2000, examples=[500])


class PlanRequest(WalkLimitRequest):
    query: str = Field(min_length=1, max_length=100, examples=["정형외과"])
    is_specific: bool = False
    expected_wait_s: float = Field(default=300, ge=0, le=7200)
    # 둘 다 생략 가능. weather 생략 시 "clear", speed_level 생략 시 ETA 모델이 날씨/요일/시간대로
    # 추정한다. weekday/hour는 요청에 받지 않고 서버가 요청 시각(KST) 기준으로 자동 계산한다.
    weather: str | None = Field(default=None, max_length=20, examples=["맑음"])
    speed_level: str | None = Field(default=None, max_length=10, examples=["중"])


class DepartureStationRequest(WalkLimitRequest):
    pass


class LocationResponse(BaseModel):
    ok: bool
    id: int | None = None
    location: dict | None


class PlanResponse(BaseModel):
    ok: bool
    plan: dict


class BoardingStation(BaseModel):
    station_id: int
    name: str
    station_type: str
    walk_distance_m: int
    walk_duration_s: int


class DepartureStationResponse(BaseModel):
    """`POST /api/stations/departure` 응답.

    status: ok | outside_service_area | no_accessible_boarding_station | route_api_failed
    """

    status: str = Field(examples=["ok"])
    boarding: BoardingStation | None = None
    reason: str | None = None
    applied_max_walk_m: float
    candidate_count: int = 0
    failed_station_count: int = 0
    failures: list[str] = Field(default_factory=list)


class ArrivalStationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90, examples=[37.4826])
    longitude: float = Field(ge=-180, le=180, examples=[126.9654])
    destination_name: str = Field(default="목적지", max_length=100)
    max_walk_m: float | None = Field(default=None, gt=0, le=2000, examples=[500])

    @field_validator("latitude", "longitude")
    @classmethod
    def finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("유한한 숫자여야 합니다.")
        return value


class AlightingStation(BaseModel):
    station_id: int
    name: str
    station_type: str
    walk_distance_m: int
    walk_duration_s: int


class ArrivalStationResponse(BaseModel):
    """`POST /api/stations/arrival` 응답.

    status: ok | outside_service_area | no_accessible_alighting_station | route_api_failed
    """

    status: str = Field(examples=["ok"])
    alighting: AlightingStation | None = None
    reason: str | None = None
    applied_max_walk_m: float
    candidate_count: int = 0
    failed_station_count: int = 0
    failures: list[str] = Field(default_factory=list)


class DestinationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    phone: str | None = None
    district: str | None = None
    neighborhood: str | None = None
    category: str | None = None
    detail_category: str | None = None


class DestinationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool
    destination: DestinationPayload | None = None


class DestinationConfirmResponse(BaseModel):
    status: str = Field(examples=["confirmed"])  # confirmed | cancelled
    message: str
    destination: DestinationPayload | None = None


class DestinationSearchRequest(BaseModel):
    """대분류/정확명 목적지 검색 공용 요청. 기준점은 보통 승차 정류장(단계1 결과)이다."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100, examples=["정형외과"])
    boarding_station_id: int = Field(examples=[3])


class DestinationCandidatePayload(BaseModel):
    name: str
    address: str | None = None
    latitude: float
    longitude: float
    straight_distance_m: float
    source: str
    phone: str | None = None
    district: str | None = None
    neighborhood: str | None = None
    category: str | None = None
    detail_category: str | None = None


class CategorySearchResponse(BaseModel):
    """`POST /api/destinations/category-search` 응답. status: ok | no_candidates_found"""

    status: str = Field(examples=["ok"])
    candidates: list[DestinationCandidatePayload] = Field(default_factory=list)
    reason: str | None = None
    used_radius_m: float | None = None
    radius_expanded: bool | None = None


class NameSearchResponse(BaseModel):
    """`POST /api/destinations/name-search` 응답. status: ok | no_candidates_found | search_failed"""

    status: str = Field(examples=["ok"])
    candidates: list[DestinationCandidatePayload] = Field(default_factory=list)
    reason: str | None = None


class DrtTravelTimeRequest(BaseModel):
    """정류장 간 DRT 차량 구간 소요시간 계산 요청.

    boarding_walk_duration_s/alighting_walk_duration_s를 함께 보내면
    응답의 total_travel_time_s(보행+차량+보행 합산)도 계산해 준다.
    """

    model_config = ConfigDict(extra="forbid")

    boarding_station_id: int = Field(examples=[3])
    alighting_station_id: int = Field(examples=[1])
    weather: str | None = Field(default=None, max_length=20, examples=["맑음"])
    speed_level: str | None = Field(default=None, max_length=10, examples=["중"])
    boarding_walk_duration_s: float | None = Field(default=None, ge=0)
    alighting_walk_duration_s: float | None = Field(default=None, ge=0)


class DrtTravelTimeResponse(BaseModel):
    distance_m: int = Field(ge=0)
    duration_s: int = Field(ge=0)
    source: str
    total_travel_time_s: float | None = None


def validate_location_quality(
    payload: LocationRequest,
    *,
    max_accuracy_m: float,
    max_age_s: int,
) -> dict:
    if payload.accuracy is not None and payload.accuracy > max_accuracy_m:
        raise ValueError(
            f"위치 정확도가 낮습니다: {payload.accuracy:.1f}m (허용 {max_accuracy_m:g}m)"
        )
    age_s = None
    if payload.captured_at is not None:
        captured = payload.captured_at
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
        if age_s > max_age_s:
            raise ValueError(f"위치 정보가 오래되었습니다: {age_s:.0f}초 (허용 {max_age_s}초)")
        if age_s < -30:
            raise ValueError("captured_at이 현재보다 30초 이상 미래입니다.")
    return {"status": "valid", "accuracy_m": payload.accuracy, "age_s": age_s}
