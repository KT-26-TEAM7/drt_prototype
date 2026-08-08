import unittest
from threading import Barrier
from unittest.mock import patch

from app.db.models import Stop, Vehicle, VehicleStatus
from app.services.dispatch import find_nearest_available_vehicle
from app.services.routing import RoutePath
from tests.helpers import create_test_database


class DispatchServiceTest(unittest.TestCase):
    def test_candidate_routes_are_requested_in_parallel(self):
        engine, session_factory = create_test_database()
        barrier = Barrier(2)

        def route_for_vehicle(start_latitude, start_longitude, *destination):
            del start_longitude, destination
            barrier.wait(timeout=1)
            duration = 60 if start_latitude == 37.47 else 120
            return RoutePath(
                ((start_latitude, 126.96), (37.48, 126.97)),
                distance_m=1000,
                source="tmap",
                duration_seconds=duration,
            )

        try:
            with session_factory() as db:
                departure = Stop(
                    id="1",
                    name="출발",
                    latitude=37.48,
                    longitude=126.97,
                )
                db.add_all(
                    [
                        departure,
                        Vehicle(
                            id="VEHICLE-001",
                            latitude=37.47,
                            longitude=126.96,
                            nearest_stop_id="1",
                            status=VehicleStatus.AVAILABLE.value,
                        ),
                        Vehicle(
                            id="VEHICLE-002",
                            latitude=37.46,
                            longitude=126.95,
                            nearest_stop_id="1",
                            status=VehicleStatus.AVAILABLE.value,
                        ),
                    ]
                )
                db.commit()

                with patch(
                    "app.services.dispatch.get_driving_route",
                    side_effect=route_for_vehicle,
                ):
                    result = find_nearest_available_vehicle(db, departure)

            self.assertEqual(result[0].id, "VEHICLE-001")
            self.assertEqual(result[2], 60)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
