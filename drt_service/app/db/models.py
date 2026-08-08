"""정류장/위치이력/예약 SQLAlchemy 모델.

`drt_` 접두사 테이블명은 기존(raw aiosqlite) 스키마를 그대로 유지한 것이다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Station(Base):
    """DRT 전용 정류장(일반 대중교통 아님)."""

    __tablename__ = "drt_station"
    __table_args__ = (CheckConstraint("station_id >= 0", name="ck_station_id_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    station_type: Mapped[str] = mapped_column(nullable=False)
    lat: Mapped[float] = mapped_column(nullable=False)
    lon: Mapped[float] = mapped_column(nullable=False)
    coverage_radius_m: Mapped[float] = mapped_column(nullable=False, default=700.0)
    walk_limit_m: Mapped[float] = mapped_column(nullable=False, default=500.0)
    ext_id: Mapped[str | None] = mapped_column(nullable=True)
    is_active: Mapped[int] = mapped_column(nullable=False, default=1)
    updated_at: Mapped[str] = mapped_column(nullable=False, default=_utc_now_iso)


class LocationPing(Base):
    """사용자 위치 수신 이력."""

    __tablename__ = "drt_locationping"
    __table_args__ = (Index("idx_locationping_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    accuracy: Mapped[float | None] = mapped_column(nullable=True)
    captured_at: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(nullable=False, default=_utc_now_iso)


class Reservation(Base):
    """DRT 예약(배차 요청) 이력."""

    __tablename__ = "drt_reservation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(unique=True, nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    boarding_station_id: Mapped[int] = mapped_column(nullable=False)
    alighting_station_id: Mapped[int] = mapped_column(nullable=False)
    expected_wait_s: Mapped[float | None] = mapped_column(nullable=True)
    requested_at: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(nullable=False, default=_utc_now_iso)
