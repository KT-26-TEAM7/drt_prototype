import unittest
from datetime import datetime, timedelta

from app.db.models import Call, CallStatus, Stop, Vehicle, VehicleStatus
from app.services.call_state import synchronize_vehicle_states
from tests.helpers import DatabaseTestCase


class CallStateServiceTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 8, 4, 12, 0, 0)
        self.db.add_all(
            [
                Stop(id="1", name="출발", latitude=37.48, longitude=126.97),
                Stop(id="2", name="도착", latitude=37.49, longitude=126.98),
                Vehicle(
                    id="VEHICLE-001",
                    latitude=37.49,
                    longitude=126.98,
                    nearest_stop_id="2",
                    status=VehicleStatus.DISPATCHED.value,
                    current_call_id="CALL-001",
                ),
            ]
        )
        self.db.commit()
        self.db.add(
            Call(
                id="CALL-001",
                vehicle_id="VEHICLE-001",
                departure_stop_id="1",
                arrival_stop_id="2",
                status=CallStatus.COMPLETED.value,
                estimated_arrival_seconds=0,
                approach_travel_seconds=60,
                stop_to_stop_travel_seconds=120,
                created_at=self.now - timedelta(minutes=10),
                updated_at=self.now - timedelta(minutes=1),
            )
        )
        self.db.commit()

    def test_completed_call_releases_dispatched_vehicle(self):
        synchronize_vehicle_states(self.db)

        vehicle = self.db.get(Vehicle, "VEHICLE-001")
        call = self.db.get(Call, "CALL-001")

        self.assertEqual(vehicle.status, VehicleStatus.AVAILABLE.value)
        self.assertIsNone(vehicle.current_call_id)
        self.assertEqual(call.status, CallStatus.COMPLETED.value)

    def test_stale_call_cannot_overwrite_vehicle_position(self):
        stale_call = Call(
            id="CALL-OLD",
            vehicle_id="VEHICLE-001",
            departure_stop_id="2",
            arrival_stop_id="1",
            status=CallStatus.APPROACHING.value,
            estimated_arrival_seconds=30,
            approach_start_latitude=37.0,
            approach_start_longitude=126.0,
            approach_travel_seconds=3600,
            stop_to_stop_travel_seconds=120,
            created_at=self.now,
            updated_at=self.now,
        )
        current_call = self.db.get(Call, "CALL-001")
        current_call.status = CallStatus.APPROACHING.value
        current_call.created_at = datetime.now()
        current_call.approach_start_latitude = 37.49
        current_call.approach_start_longitude = 126.98
        current_call.approach_travel_seconds = 3600
        self.db.add(stale_call)
        self.db.commit()

        synchronize_vehicle_states(self.db)

        vehicle = self.db.get(Vehicle, "VEHICLE-001")
        self.assertGreater(vehicle.latitude, 37.4)
        self.assertGreater(vehicle.longitude, 126.9)
        self.assertEqual(stale_call.status, CallStatus.APPROACHING.value)


if __name__ == "__main__":
    unittest.main()
