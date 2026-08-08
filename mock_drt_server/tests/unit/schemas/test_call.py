import unittest

from pydantic import ValidationError

from app.schemas.call import CallCreateRequest, CallCreateResponse


class CallSchemaTest(unittest.TestCase):
    def test_request_strips_stop_ids(self):
        request = CallCreateRequest(
            departure_stop_id=" 1 ",
            arrival_stop_id=" 2 ",
            stop_to_stop_travel_seconds=180,
        )

        self.assertEqual(request.departure_stop_id, "1")
        self.assertEqual(request.arrival_stop_id, "2")

    def test_request_rejects_blank_stop_id(self):
        with self.assertRaises(ValidationError):
            CallCreateRequest(
                departure_stop_id=" ",
                arrival_stop_id="2",
                stop_to_stop_travel_seconds=180,
            )

    def test_request_rejects_travel_time_outside_range(self):
        for travel_seconds in (0, 7201):
            with self.subTest(travel_seconds=travel_seconds):
                with self.assertRaises(ValidationError):
                    CallCreateRequest(
                        departure_stop_id="1",
                        arrival_stop_id="2",
                        stop_to_stop_travel_seconds=travel_seconds,
                    )

    def test_response_rejects_unknown_status(self):
        with self.assertRaises(ValidationError):
            CallCreateResponse(
                call_id="CALL-001",
                vehicle_id="VEHICLE-001",
                call_status="UNKNOWN",
                estimated_arrival_seconds=60,
                approach_travel_seconds=60,
                stop_to_stop_travel_seconds=180,
                vehicle_latitude=37.48,
                vehicle_longitude=126.97,
                nearest_stop_id="1",
                tracking_url="http://localhost:8000/tracking/token",
                tracking_message="예약 완료",
            )


if __name__ == "__main__":
    unittest.main()
