import unittest
from unittest.mock import patch

from app.services.routing import _parse_tmap_coordinates, get_driving_route


class RoutingServiceTest(unittest.TestCase):
    def test_tmap_segments_are_sorted_numerically_and_oriented_continuously(self):
        body = {
            "features": [
                {
                    "properties": {"index": "10"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[126.99, 37.50], [126.98, 37.49]],
                    },
                },
                {
                    "properties": {"index": "2"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[126.98, 37.49], [126.97, 37.48]],
                    },
                },
            ]
        }

        coordinates = _parse_tmap_coordinates(body, 37.48, 126.97)

        self.assertEqual(
            coordinates,
            (
                (37.48, 126.97),
                (37.49, 126.98),
                (37.50, 126.99),
            ),
        )

    def test_tmap_failure_uses_straight_route(self):
        with (
            patch("app.services.routing.TMAP_APP_KEY", "test-key"),
            patch("app.services.routing.urlopen", side_effect=TimeoutError),
        ):
            route = get_driving_route(37.48, 126.97, 37.49, 126.98)

        self.assertEqual(route.source, "straight_fallback")
        self.assertEqual(
            route.coordinates,
            ((37.48, 126.97), (37.49, 126.98)),
        )
        self.assertIsNone(route.duration_seconds)


if __name__ == "__main__":
    unittest.main()
