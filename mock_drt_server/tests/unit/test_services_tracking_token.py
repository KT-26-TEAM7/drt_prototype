import unittest
from unittest.mock import patch

from app.services.tracking_token import build_tracking_url


class TrackingUrlTest(unittest.TestCase):
    def test_token_is_added_as_query_parameter(self):
        with patch(
            "app.services.tracking_token.TRACKING_BASE_URL",
            "https://example.onrender.com/tracking",
        ):
            self.assertEqual(
                build_tracking_url("public-token"),
                "https://example.onrender.com/tracking?token=public-token",
            )

    def test_existing_query_parameters_are_preserved(self):
        with patch(
            "app.services.tracking_token.TRACKING_BASE_URL",
            "https://example.com/dashboard?lang=ko",
        ):
            self.assertEqual(
                build_tracking_url("public-token"),
                "https://example.com/dashboard?lang=ko&token=public-token",
            )


if __name__ == "__main__":
    unittest.main()
