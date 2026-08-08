from datetime import datetime, timedelta
from unittest.mock import patch

from app.db.models import Call, CallStatus, Stop, TrackingToken, Vehicle
from app.services.tracking import get_tracking
from app.services.tracking_token import hash_tracking_token
from tests.helpers import DatabaseTestCase


class TrackingServiceTest(DatabaseTestCase):
    raw_token = "tracking-token"

    def setUp(self):
        super().setUp()
        now = datetime(2026, 8, 4, 12, 0, 0)
        self.now = now
        self.db.add_all(
            [
                Stop(id="1", name="출발", latitude=37.48, longitude=126.97),
                Stop(id="2", name="도착", latitude=37.49, longitude=126.98),
                Vehicle(
                    id="VEHICLE-001",
                    latitude=37.475,
                    longitude=126.965,
                    nearest_stop_id="1",
                    status="DISPATCHED",
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
                status=CallStatus.APPROACHING.value,
                estimated_arrival_seconds=30,
                approach_start_latitude=37.47,
                approach_start_longitude=126.96,
                approach_travel_seconds=90,
                stop_to_stop_travel_seconds=180,
                created_at=now,
                updated_at=now,
            )
        )
        self.db.commit()
        self.db.add(
            TrackingToken(
                id="TRACK-001",
                call_id="CALL-001",
                token_hash=hash_tracking_token(self.raw_token),
                expires_at=now + timedelta(hours=1),
                created_at=now,
            )
        )
        self.db.commit()

    def test_missing_approach_route_uses_straight_route_without_writing(self):
        with patch(
            "app.services.routing.get_driving_route",
            side_effect=AssertionError("tracking 조회에서 경로 API를 호출하면 안 됩니다."),
        ):
            response = get_tracking(self.db, self.raw_token, self.now)

        call = self.db.get(Call, "CALL-001")
        self.assertEqual(response.route.source, "straight_fallback")
        self.assertEqual([stop.name for stop in response.stops], ["출발", "도착"])
        self.assertEqual(
            response.route.coordinates,
            [(37.47, 126.96), (37.48, 126.97)],
        )
        self.assertIsNone(call.approach_route_coordinates)
        self.assertIsNone(call.approach_route_source)
        self.assertFalse(self.db.dirty)

    def test_missing_service_route_uses_straight_route_without_writing(self):
        call = self.db.get(Call, "CALL-001")
        call.status = CallStatus.IN_SERVICE.value
        self.db.commit()

        response = get_tracking(self.db, self.raw_token, self.now)

        self.assertEqual(response.route.source, "straight_fallback")
        self.assertEqual(
            response.route.coordinates,
            [(37.48, 126.97), (37.49, 126.98)],
        )
        self.assertIsNone(call.service_route_coordinates)
        self.assertIsNone(call.service_route_source)
        self.assertFalse(self.db.dirty)


if __name__ == "__main__":
    import unittest

    unittest.main()
