"""POST /api/stations/arrival 및 find_arrival_station 검증."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.clients.tmap_client import Coordinate, MockTmapClient
from app.stations.find_arrival_station import find_arrival_station
from tests.conftest import make_client

SADANG = Coordinate(37.4849, 126.9710)
SUWON = Coordinate(37.2861138, 127.0458013)


def test_outside_service_area(stations):
    result = asyncio.run(find_arrival_station(SUWON, "목적지", stations, MockTmapClient(), 500))
    assert result["status"] == "outside_service_area"
    assert result["alighting"] is None


def test_picks_nearest_walkable_station(stations):
    result = asyncio.run(find_arrival_station(SADANG, "목적지", stations, MockTmapClient(), 500))
    assert result["status"] == "ok"
    assert result["alighting"]["walk"].distance_m <= 500


def test_walk_limit_excludes_all_stations(stations):
    result = asyncio.run(find_arrival_station(SADANG, "목적지", stations, MockTmapClient(), 1))
    assert result["status"] == "no_accessible_alighting_station"


def test_endpoint_returns_alighting_station(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/stations/arrival", json={
            "latitude": SADANG.lat, "longitude": SADANG.lon,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["alighting"]["station_id"] > 0
        assert body["applied_max_walk_m"] > 0


def test_endpoint_outside_service_area(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/stations/arrival", json={
            "latitude": SUWON.lat, "longitude": SUWON.lon,
        })
        assert response.status_code == 200
        assert response.json()["status"] == "outside_service_area"
