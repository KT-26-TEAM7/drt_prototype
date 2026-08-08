import unittest
from datetime import datetime

from fastapi import HTTPException

from app.api.calls import get_call_status
from app.db.models import Call, CallStatus, Stop, Vehicle, VehicleStatus
from tests.helpers import DatabaseTestCase


class CallStatusApiTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.updated_at = datetime(2026, 8, 4, 12, 0, 0)
        self.db.add_all(
            [
                Stop(id="1", name="출발", latitude=37.48, longitude=126.97),
                Stop(id="2", name="도착", latitude=37.49, longitude=126.98),
                Vehicle(
                    id="VEHICLE-001",
                    latitude=37.475,
                    longitude=126.965,
                    nearest_stop_id="1",
                    status=VehicleStatus.DISPATCHED.value,
                    current_call_id="CALL-001",
                ),
            ]
        )
        self.db.commit()

    def add_call(
        self,
        call_id="CALL-001",
        status=CallStatus.APPROACHING.value,
        approach_seconds=90,
        service_seconds=180,
        vehicle_id="VEHICLE-001",
    ):
        self.db.add(
            Call(
                id=call_id,
                vehicle_id=vehicle_id,
                departure_stop_id="1",
                arrival_stop_id="2",
                status=status,
                estimated_arrival_seconds=30,
                approach_travel_seconds=approach_seconds,
                stop_to_stop_travel_seconds=service_seconds,
                updated_at=self.updated_at,
            )
        )
        self.db.commit()

    def test_active_call_returns_current_vehicle_position(self):
        self.add_call()

        response = get_call_status("CALL-001", self.db)

        self.assertEqual(response.call_status, "APPROACHING")
        self.assertEqual(response.vehicle_latitude, 37.475)
        self.assertEqual(response.vehicle_longitude, 126.965)
        self.assertEqual(response.updated_at, self.updated_at)

    def test_completed_call_returns_arrival_stop_position(self):
        self.add_call(status=CallStatus.COMPLETED.value)
        vehicle = self.db.get(Vehicle, "VEHICLE-001")
        vehicle.latitude = 37.51
        vehicle.longitude = 127.01
        vehicle.nearest_stop_id = "1"
        self.db.commit()

        response = get_call_status("CALL-001", self.db)

        self.assertEqual(response.call_status, "COMPLETED")
        self.assertEqual(response.vehicle_latitude, 37.49)
        self.assertEqual(response.vehicle_longitude, 126.98)
        self.assertEqual(response.nearest_stop_id, "2")

    def test_legacy_missing_travel_times_are_returned_as_null(self):
        self.add_call(approach_seconds=None, service_seconds=None)

        response = get_call_status("CALL-001", self.db)

        self.assertIsNone(response.approach_travel_seconds)
        self.assertIsNone(response.stop_to_stop_travel_seconds)

    def test_missing_call_returns_not_found(self):
        with self.assertRaises(HTTPException) as context:
            get_call_status("CALL-MISSING", self.db)

        self.assertEqual(context.exception.status_code, 404)

if __name__ == "__main__":
    unittest.main()
