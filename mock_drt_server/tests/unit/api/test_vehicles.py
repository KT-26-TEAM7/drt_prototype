import unittest

from app.api.vehicles import get_vehicles
from app.db.models import Stop, Vehicle, VehicleStatus
from tests.helpers import create_test_database


class VehiclesApiTest(unittest.TestCase):
    def setUp(self):
        self.engine, self.session_factory = create_test_database()

    def tearDown(self):
        self.engine.dispose()

    def test_get_vehicles_returns_expected_fields(self):
        with self.session_factory() as db:
            db.add(
                Stop(
                    id="3",
                    name="남성역",
                    latitude=37.48479351,
                    longitude=126.9709102,
                )
            )
            db.add_all(
                [
                    Vehicle(
                        id="VEHICLE-001",
                        latitude=37.48479351,
                        longitude=126.9709102,
                        nearest_stop_id="3",
                        status=VehicleStatus.AVAILABLE.value,
                        current_call_id=None,
                    ),
                    Vehicle(
                        id="VEHICLE-002",
                        latitude=37.485,
                        longitude=126.971,
                        nearest_stop_id="3",
                        status=VehicleStatus.DISPATCHED.value,
                        current_call_id="CALL-001",
                    ),
                ]
            )
            db.commit()

            response = get_vehicles(db)

        self.assertEqual(len(response), 2)
        self.assertEqual(
            set(response[0]),
            {
                "vehicle_id",
                "latitude",
                "longitude",
                "nearest_stop_id",
                "status",
                "current_call_id",
            },
        )
        self.assertIsNone(response[0]["current_call_id"])
        self.assertEqual(response[1]["current_call_id"], "CALL-001")

    def test_get_vehicles_returns_empty_list(self):
        with self.session_factory() as db:
            self.assertEqual(get_vehicles(db), [])


if __name__ == "__main__":
    unittest.main()
