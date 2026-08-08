"""POST /api/travel-time/drt 검증 (5~6단계: DRT 차량시간 + 총 합산 시간 단독 확인)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import make_client

BOARDING_STATION_ID = 3   # 남성역
ALIGHTING_STATION_ID = 5  # 동작고등학교


def test_drt_travel_time_returns_eta_estimate(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/travel-time/drt", json={
            "boarding_station_id": BOARDING_STATION_ID,
            "alighting_station_id": ALIGHTING_STATION_ID,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["distance_m"] > 0
        assert body["duration_s"] > 0
        assert body["source"]
        assert body["total_travel_time_s"] is None  # 도보시간을 안 보냈으므로


def test_drt_travel_time_computes_total_with_walk_durations(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/travel-time/drt", json={
            "boarding_station_id": BOARDING_STATION_ID,
            "alighting_station_id": ALIGHTING_STATION_ID,
            "boarding_walk_duration_s": 39,
            "alighting_walk_duration_s": 19,
        })
        assert response.status_code == 200
        body = response.json()
        # total_travel_time_s는 반올림 전 원시 duration으로 계산되므로, 이미 반올림된
        # 응답의 duration_s 합과는 최대 1초 오차가 날 수 있다(tests/test_api.py와 동일 패턴).
        assert body["total_travel_time_s"] == pytest.approx(39 + body["duration_s"] + 19, abs=1)


def test_drt_travel_time_uses_weather_speed_level(tmp_path: Path):
    with make_client(tmp_path) as client:
        baseline = client.post("/api/travel-time/drt", json={
            "boarding_station_id": BOARDING_STATION_ID,
            "alighting_station_id": ALIGHTING_STATION_ID,
        }).json()
        rainy_slow = client.post("/api/travel-time/drt", json={
            "boarding_station_id": BOARDING_STATION_ID,
            "alighting_station_id": ALIGHTING_STATION_ID,
            "weather": "비",
            "speed_level": "하",
        }).json()
        assert rainy_slow["duration_s"] != baseline["duration_s"]


def test_drt_travel_time_unknown_boarding_station_returns_404(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/travel-time/drt", json={
            "boarding_station_id": 9999,
            "alighting_station_id": ALIGHTING_STATION_ID,
        })
        assert response.status_code == 404


def test_drt_travel_time_unknown_alighting_station_returns_404(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/travel-time/drt", json={
            "boarding_station_id": BOARDING_STATION_ID,
            "alighting_station_id": 9999,
        })
        assert response.status_code == 404
