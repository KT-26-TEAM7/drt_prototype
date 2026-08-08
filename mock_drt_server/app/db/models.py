from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"


class CallStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    APPROACHING = "APPROACHING"
    ARRIVED = "ARRIVED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"


class Stop(Base):
    __tablename__ = "stops"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    nearest_stop_id: Mapped[str] = mapped_column(
        ForeignKey("stops.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String,
        default=VehicleStatus.AVAILABLE.value,
        nullable=False,
    )
    current_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    roaming_start_latitude: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    roaming_start_longitude: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    roaming_end_latitude: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    roaming_end_longitude: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    roaming_started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    roaming_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    roaming_route_coordinates: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    roaming_route_source: Mapped[str | None] = mapped_column(
        String, nullable=True
    )


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id"), nullable=False
    )
    departure_stop_id: Mapped[str] = mapped_column(
        ForeignKey("stops.id"), nullable=False
    )
    arrival_stop_id: Mapped[str] = mapped_column(
        ForeignKey("stops.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String,
        default=CallStatus.DISPATCHED.value,
        nullable=False,
    )
    estimated_arrival_seconds: Mapped[int] = mapped_column(nullable=False)
    approach_start_latitude: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    approach_start_longitude: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    approach_travel_seconds: Mapped[int | None] = mapped_column(nullable=True)
    stop_to_stop_travel_seconds: Mapped[int | None] = mapped_column(nullable=True)
    approach_route_coordinates: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    approach_route_source: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    service_route_coordinates: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    service_route_source: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )


class TrackingToken(Base):
    __tablename__ = "tracking_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    call_id: Mapped[str] = mapped_column(
        ForeignKey("calls.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        nullable=False,
    )
