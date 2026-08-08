import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException
from sqlalchemy import select

from app.api.calls import create_call
from app.db.models import Call, Stop, TrackingToken, Vehicle, VehicleStatus
from app.schemas.call import CallCreateRequest
from app.services.routing import RoutePath, deserialize_route
from app.services.tracking_token import hash_tracking_token
from tests.helpers import DatabaseTestCase


class CallsApiTest(DatabaseTestCase):

    def seed_dispatchable_vehicle(self, status=VehicleStatus.AVAILABLE.value):
        self.db.add_all(
            [
                Stop(id="1", name="출발", latitude=37.48, longitude=126.97),
                Stop(id="2", name="도착", latitude=37.49, longitude=126.98),
                Vehicle(
                    id="VEHICLE-001",
                    latitude=37.47,
                    longitude=126.96,
                    nearest_stop_id="1",
                    status=status,
                    current_call_id=None,
                ),
            ]
        )
        self.db.commit()

    def request(self, departure="1", arrival="2", travel_seconds=180):
        return CallCreateRequest(
            departure_stop_id=departure,
            arrival_stop_id=arrival,
            stop_to_stop_travel_seconds=travel_seconds,
        )

    def test_create_call_persists_call_vehicle_and_hashed_tracking_token(self):
        self.seed_dispatchable_vehicle()
        approach_route = RoutePath(
            ((37.47, 126.96), (37.48, 126.97)),
            distance_m=1500,
            source="tmap",
            duration_seconds=90,
        )
        service_route = RoutePath(
            ((37.48, 126.97), (37.49, 126.98)),
            distance_m=1800,
            source="tmap",
            duration_seconds=999,
        )

        with (
            patch("app.api.calls.synchronize_vehicle_states"),
            patch(
                "app.api.calls.find_nearest_available_vehicle",
                return_value=(
                    self.db.get(Vehicle, "VEHICLE-001"),
                    approach_route,
                    90,
                ),
            ),
            patch("app.api.calls.get_driving_route", return_value=service_route),
        ):
            response = create_call(self.request(), self.db)

        self.assertEqual(response.call_status, "DISPATCHED")
        self.assertEqual(response.approach_travel_seconds, 90)
        self.assertEqual(response.stop_to_stop_travel_seconds, 180)

        raw_token = parse_qs(urlsplit(str(response.tracking_url)).query)["token"][0]
        call = self.db.get(Call, response.call_id)
        vehicle = self.db.get(Vehicle, "VEHICLE-001")
        token = self.db.scalar(select(TrackingToken))
        self.assertEqual(call.stop_to_stop_travel_seconds, 180)
        self.assertEqual(len(deserialize_route(call.service_route_coordinates)), 2)
        self.assertEqual(vehicle.status, VehicleStatus.DISPATCHED.value)
        self.assertEqual(vehicle.current_call_id, call.id)
        self.assertEqual(token.token_hash, hash_tracking_token(raw_token))
        self.assertNotEqual(token.token_hash, raw_token)

    def test_same_stop_is_rejected_before_state_synchronization(self):
        with patch("app.api.calls.synchronize_vehicle_states") as synchronize:
            with self.assertRaises(HTTPException) as context:
                create_call(self.request(departure="1", arrival="1"), self.db)

        self.assertEqual(context.exception.status_code, 400)
        synchronize.assert_not_called()

    def test_missing_stop_returns_not_found_before_state_synchronization(self):
        with patch("app.api.calls.synchronize_vehicle_states") as synchronize:
            with self.assertRaises(HTTPException) as context:
                create_call(self.request(departure="missing"), self.db)

        self.assertEqual(context.exception.status_code, 404)
        synchronize.assert_not_called()

    def test_missing_arrival_stop_returns_not_found_before_state_synchronization(self):
        self.db.add(Stop(id="1", name="출발", latitude=37.48, longitude=126.97))
        self.db.commit()
        with patch("app.api.calls.synchronize_vehicle_states") as synchronize:
            with self.assertRaises(HTTPException) as context:
                create_call(self.request(arrival="missing"), self.db)

        self.assertEqual(context.exception.status_code, 404)
        synchronize.assert_not_called()

    def test_no_available_vehicle_returns_conflict(self):
        self.seed_dispatchable_vehicle(status=VehicleStatus.DISPATCHED.value)
        with patch("app.api.calls.synchronize_vehicle_states"):
            with self.assertRaises(HTTPException) as context:
                create_call(self.request(), self.db)

        self.assertEqual(context.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
