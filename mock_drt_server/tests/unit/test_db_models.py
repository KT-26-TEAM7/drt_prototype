import unittest
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.db.models import Call, Stop, TrackingToken, Vehicle
from tests.helpers import create_test_database


class DatabaseModelsTest(unittest.TestCase):
    def setUp(self):
        self.engine, self.session_factory = create_test_database()

    def tearDown(self):
        self.engine.dispose()

    def test_vehicle_requires_existing_nearest_stop(self):
        with self.session_factory() as db:
            db.add(
                Vehicle(
                    id="VEHICLE-001",
                    latitude=37.48,
                    longitude=126.97,
                    nearest_stop_id="MISSING",
                    status="AVAILABLE",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_only_one_tracking_token_is_allowed_per_call(self):
        now = datetime.now()
        with self.session_factory() as db:
            db.add_all(
                [
                    Stop(id="1", name="출발", latitude=37.48, longitude=126.97),
                    Stop(id="2", name="도착", latitude=37.49, longitude=126.98),
                    Vehicle(
                        id="VEHICLE-001",
                        latitude=37.48,
                        longitude=126.97,
                        nearest_stop_id="1",
                        status="DISPATCHED",
                    ),
                ]
            )
            db.flush()
            db.add(
                Call(
                    id="CALL-001",
                    vehicle_id="VEHICLE-001",
                    departure_stop_id="1",
                    arrival_stop_id="2",
                    status="DISPATCHED",
                    estimated_arrival_seconds=60,
                )
            )
            db.flush()
            db.add_all(
                [
                    TrackingToken(
                        id="TOKEN-001",
                        call_id="CALL-001",
                        token_hash="a" * 64,
                        expires_at=now + timedelta(hours=1),
                    ),
                    TrackingToken(
                        id="TOKEN-002",
                        call_id="CALL-001",
                        token_hash="b" * 64,
                        expires_at=now + timedelta(hours=1),
                    ),
                ]
            )
            with self.assertRaises(IntegrityError):
                db.commit()


if __name__ == "__main__":
    unittest.main()
