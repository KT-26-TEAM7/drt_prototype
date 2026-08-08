"""app/reservation/plan_route.py::vehicle_route가 prod의 위치 인자 호출 관례와 호환되는지,
정류장이 ETA 모델(StationIndex)에 없을 때 TMAP 실제 차량경로로 안전하게 폴백하는지 검증한다.

원래 이 어댑터 역할은 별도 클래스(ETAEnhancedProvider)였지만, 목표 구조에서는
`app/reservation/plan_route.py`가 직접 흡수했다.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.clients.tmap_client import MockTmapClient
from app.reservation.plan_route import vehicle_route
from app.travel_time.estimate_duration import ETAContext, ETAPredictor, ETAService, StationIndex

ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "app" / "travel_time" / "models"


@pytest.fixture
def eta_service(stations) -> ETAService:
    predictor = ETAPredictor(StationIndex(stations), artifacts_dir=ARTIFACTS_DIR)
    return ETAService(predictor)


def test_vehicle_route_uses_eta_model_when_stations_resolve(stations, eta_service):
    station_a = next(station for station in stations if station.station_id == 1)
    station_b = next(station for station in stations if station.station_id == 3)
    context = ETAContext(weather="맑음", weekday="월요일", hour=9)

    route = asyncio.run(vehicle_route(station_a, station_b, MockTmapClient(), eta_service, context))
    assert route.source != "mock_car"  # ML 예측 경로를 탔는지(폴백 아님) 확인
    assert route.duration_s > 0
    assert route.distance_m > 0


def test_vehicle_route_falls_back_to_client_when_station_unresolvable(stations):
    # ETA 모델을 정류장 하나짜리 인덱스로 만들어 나머지 정류장은 항상 조회 실패하게 한다.
    limited_service = ETAService(ETAPredictor(StationIndex(stations[:1]), artifacts_dir=ARTIFACTS_DIR))
    context = ETAContext(weather="맑음", weekday="월요일", hour=9)

    station_a, station_b = stations[1], stations[2]
    route = asyncio.run(vehicle_route(station_a, station_b, MockTmapClient(), limited_service, context))
    assert route.source == "mock_car"
