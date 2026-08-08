"""POST /api/destinations/confirm 및 confirm_destination 검증."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.destination.confirm_destination import DestinationConfirmationError, confirm_destination
from app.schemas import DestinationConfirmRequest, DestinationPayload
from tests.conftest import make_client

DESTINATION = {
    "name": "서울정형외과의원",
    "address": "서울 동작구 사당로 196",
    "latitude": 37.48499129,
    "longitude": 126.969913,
    "phone": "02-3474-4555",
    "district": "동작구",
    "neighborhood": "사당동",
    "category": "의원",
    "detail_category": "정형외과",
}


def test_confirm_destination_returns_confirmed():
    request = DestinationConfirmRequest(confirmed=True, destination=DestinationPayload(**DESTINATION))
    response = confirm_destination(request)
    assert response.status == "confirmed"
    assert "서울정형외과의원" in response.message
    assert response.destination.name == "서울정형외과의원"


def test_confirm_destination_returns_cancelled():
    request = DestinationConfirmRequest(confirmed=False, destination=None)
    response = confirm_destination(request)
    assert response.status == "cancelled"
    assert response.destination is None


def test_confirm_destination_without_destination_raises():
    request = DestinationConfirmRequest(confirmed=True, destination=None)
    with pytest.raises(DestinationConfirmationError):
        confirm_destination(request)


def test_endpoint_confirmed(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/confirm", json={
            "confirmed": True, "destination": DESTINATION,
        })
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "confirmed"
        assert body["destination"]["name"] == "서울정형외과의원"


def test_endpoint_cancelled(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/confirm", json={
            "confirmed": False, "destination": None,
        })
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"


def test_endpoint_confirmed_without_destination_returns_400(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post("/api/destinations/confirm", json={
            "confirmed": True, "destination": None,
        })
        assert response.status_code == 400
