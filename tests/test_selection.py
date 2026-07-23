import math
import unittest

from balc_flights_led.models import Coordinates, Flight
from balc_flights_led.selection import (
    bounds_around,
    distance_nautical_miles,
    initial_bearing_degrees,
    nearest_flight,
)


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = Coordinates(latitude=47.6175, longitude=-122.305)

    def test_one_latitude_minute_is_about_one_nautical_mile(self) -> None:
        destination = Coordinates(
            latitude=self.origin.latitude + (1 / 60),
            longitude=self.origin.longitude,
        )

        self.assertAlmostEqual(
            distance_nautical_miles(self.origin, destination),
            1.0,
            delta=0.01,
        )
        self.assertAlmostEqual(initial_bearing_degrees(self.origin, destination), 0.0)

    def test_nearest_flight_excludes_ground_and_stale_rows(self) -> None:
        flights = [
            Flight(
                callsign="GROUND1",
                position=Coordinates(47.618, -122.305),
                on_ground=True,
                seen_seconds_ago=1,
            ),
            Flight(
                callsign="STALE1",
                position=Coordinates(47.619, -122.305),
                seen_seconds_ago=61,
            ),
            Flight(
                callsign="FAR123",
                position=Coordinates(47.65, -122.305),
                seen_seconds_ago=1,
            ),
            Flight(
                callsign="NEAR12",
                position=Coordinates(47.625, -122.305),
                seen_seconds_ago=2,
            ),
        ]

        result = nearest_flight(flights, self.origin)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.flight.callsign, "NEAR12")
        self.assertLess(result.distance_nautical_miles, 0.5)

    def test_bounds_are_centered_and_cover_requested_radius(self) -> None:
        bounds = bounds_around(self.origin, radius_nautical_miles=20)

        self.assertAlmostEqual(
            (bounds.minimum_latitude + bounds.maximum_latitude) / 2,
            self.origin.latitude,
        )
        self.assertAlmostEqual(
            (bounds.minimum_longitude + bounds.maximum_longitude) / 2,
            self.origin.longitude,
        )
        northern_edge = Coordinates(bounds.maximum_latitude, self.origin.longitude)
        self.assertTrue(
            math.isclose(
                distance_nautical_miles(self.origin, northern_edge),
                20,
                rel_tol=0.002,
            )
        )

    def test_invalid_coordinate_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "latitude"):
            Coordinates(latitude=91, longitude=0)


if __name__ == "__main__":
    unittest.main()
