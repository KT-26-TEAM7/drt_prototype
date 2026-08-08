from __future__ import annotations

from pathlib import Path

from tests.conftest import make_client


def test_departure_station_ok(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/stations/departure", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["boarding"]["station_id"] > 0


def test_departure_station_outside_service_area(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/stations/departure", json={
            "latitude": 37.2861138,
            "longitude": 127.0458013,
        })
        assert response.status_code == 200
        assert response.json()["status"] == "outside_service_area"


def test_reservation_confirmed_for_drt_recommendation(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/reservations", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "남현서울정형외과",
            "is_specific": True,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["plan"]["recommended_mode"] == "drt"
        assert body["reservation"]["status"] == "accepted"
        assert body["reservation"]["call_id"]


def test_reservation_not_required_for_walk_recommendation(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/reservations", json={
            "latitude": 37.4849,
            "longitude": 126.9710,
            "query": "사당정형외과의원",
            "is_specific": True,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["plan"]["recommended_mode"] == "walk"
        assert body["reservation"] is None
        assert body["ok"] is True
