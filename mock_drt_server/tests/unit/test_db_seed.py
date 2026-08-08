import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from app.core.config import VEHICLE_COUNT
from app.db.models import Stop, Vehicle, VehicleStatus
from app.db.seed import initialize_stops, initialize_vehicles, load_stops_from_csv
from tests.helpers import DatabaseTestCase


class DatabaseSeedTest(DatabaseTestCase):
    def test_stop_csv_has_unique_valid_records(self):
        stops = load_stops_from_csv()
        stop_ids = {stop.id for stop in stops}

        self.assertTrue(stops)
        self.assertEqual(len(stop_ids), len(stops))
        for stop in stops:
            self.assertTrue(stop.name.strip())
            self.assertGreaterEqual(stop.latitude, -90)
            self.assertLessEqual(stop.latitude, 90)
            self.assertGreaterEqual(stop.longitude, -180)
            self.assertLessEqual(stop.longitude, 180)

    def test_initialize_stops_adds_only_missing_csv_records(self):
        seeds = load_stops_from_csv()
        first = seeds[0]
        self.db.add(
            Stop(
                id=first.id,
                name="기존 이름",
                latitude=first.latitude,
                longitude=first.longitude,
            )
        )
        self.db.commit()

        initialize_stops(self.db)

        self.assertEqual(self.db.scalar(select(func.count(Stop.id))), len(seeds))
        self.assertEqual(self.db.get(Stop, first.id).name, "기존 이름")

    def test_initialize_vehicles_adds_only_missing_configured_vehicles(self):
        self.db.add_all(
            [
                Stop(id="1", name="A", latitude=37.48, longitude=126.97),
                Stop(id="2", name="B", latitude=37.49, longitude=126.98),
                Vehicle(
                    id="VEHICLE-001",
                    latitude=37.48,
                    longitude=126.97,
                    nearest_stop_id="1",
                    status=VehicleStatus.AVAILABLE.value,
                ),
            ]
        )
        self.db.commit()

        with patch("app.db.seed.start_vehicle_roaming") as start_roaming:
            initialize_vehicles(self.db)

        vehicle_ids = set(self.db.scalars(select(Vehicle.id)).all())
        self.assertEqual(
            vehicle_ids,
            {f"VEHICLE-{index:03d}" for index in range(1, VEHICLE_COUNT + 1)},
        )
        self.assertEqual(start_roaming.call_count, VEHICLE_COUNT - 1)

    def test_initialize_vehicles_requires_stops(self):
        with self.assertRaisesRegex(RuntimeError, "정류장이 없습니다"):
            initialize_vehicles(self.db)


if __name__ == "__main__":
    unittest.main()
