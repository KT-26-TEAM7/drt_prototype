import unittest

from pydantic import ValidationError

from app.schemas.stop import StopResponse

class StopResponseTest(unittest.TestCase):
    def test_valid_stop_response(self):
        response = StopResponse(
            stop_id="3",
            stop_name="남성역",
            latitude=37.48479351,
            longitude=126.9709102,
        )
        self.assertEqual(response.stop_id, "3")
        self.assertEqual(response.stop_name, "남성역")

    def test_invalid_coordinates_are_rejected(self):
        with self.assertRaises(ValidationError):
            StopResponse(
                stop_id="3",
                stop_name="남성역",
                latitude=91,
                longitude=126.9709102,
            )

if __name__ == "__main__":
    unittest.main()