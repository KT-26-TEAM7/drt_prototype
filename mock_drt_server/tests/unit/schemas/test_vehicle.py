import unittest

from pydantic import ValidationError

from app.schemas.vehicle import VehicleResponse


class VehicleResponseTest(unittest.TestCase):
    def test_valid_available_vehicle_response(self):
        response = VehicleResponse(
            vehicle_id="VEHICLE-001",
            latitude=37.48479351,
            longitude=126.9709102,
            nearest_stop_id="3",
            status="AVAILABLE",
            current_call_id=None,
        )

        self.assertEqual(response.status, "AVAILABLE")
        self.assertIsNone(response.current_call_id)

    def test_valid_dispatched_vehicle_response(self):
        response = VehicleResponse(
            vehicle_id="VEHICLE-001",
            latitude=37.48479351,
            longitude=126.9709102,
            nearest_stop_id="3",
            status="DISPATCHED",
            current_call_id="CALL-001",
        )

        self.assertEqual(response.current_call_id, "CALL-001")

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValidationError):
            VehicleResponse(
                vehicle_id="VEHICLE-001",
                latitude=37.48479351,
                longitude=126.9709102,
                nearest_stop_id="3",
                status="UNKNOWN",
                current_call_id=None,
            )

    def test_invalid_coordinates_are_rejected(self):
        with self.assertRaises(ValidationError):
            VehicleResponse(
                vehicle_id="VEHICLE-001",
                latitude=37.48479351,
                longitude=181,
                nearest_stop_id="3",
                status="AVAILABLE",
                current_call_id=None,
            )


if __name__ == "__main__":
    unittest.main()
