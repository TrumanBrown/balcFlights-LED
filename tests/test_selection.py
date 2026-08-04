import math
import unittest

from balc_flights_led.models import Coordinates, Flight, Projection
from balc_flights_led.selection import (
    MAXIMUM_PROJECTION_SECONDS,
    bounds_around,
    distance_nautical_miles,
    estimated_position,
    initial_bearing_degrees,
    nearest_flight,
)


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = Coordinates(latitude=47.6175, longitude=-122.305)

    def test_projection_is_preferred_over_the_raw_fix(self) -> None:
        flight = Flight(
            position=Coordinates(47.70, -122.305),
            projection=Projection(position=Coordinates(47.65, -122.305), seconds=3.0),
        )

        self.assertEqual(estimated_position(flight), Coordinates(47.65, -122.305))

    def test_local_extrapolation_advances_along_the_heading(self) -> None:
        flight = Flight(
            position=Coordinates(47.60, -122.305),
            speed_knots=600.0,
            heading_degrees=0.0,
            projection=Projection(position=Coordinates(47.60, -122.305), seconds=0.0),
        )

        moved = estimated_position(flight, elapsed_seconds=30.0)

        self.assertAlmostEqual(distance_nautical_miles(flight.position, moved), 5.0, delta=0.01)
        self.assertAlmostEqual(initial_bearing_degrees(flight.position, moved), 0.0, delta=0.01)

    def test_extrapolation_stops_at_the_documented_ceiling(self) -> None:
        flight = Flight(
            position=Coordinates(47.60, -122.305),
            speed_knots=600.0,
            heading_degrees=0.0,
            projection=Projection(position=Coordinates(47.60, -122.305), seconds=5.0),
        )

        capped = estimated_position(flight, elapsed_seconds=600.0)

        self.assertAlmostEqual(
            distance_nautical_miles(flight.position, capped),
            600.0 * (MAXIMUM_PROJECTION_SECONDS - 5.0) / 3600.0,
            delta=0.01,
        )

    def test_grounded_or_unknown_movement_is_never_extrapolated(self) -> None:
        stationary = Flight(position=Coordinates(47.60, -122.305))
        grounded = Flight(
            position=Coordinates(47.60, -122.305),
            speed_knots=600.0,
            heading_degrees=0.0,
            on_ground=True,
        )

        self.assertEqual(estimated_position(stationary, 30.0), stationary.position)
        self.assertEqual(estimated_position(grounded, 30.0), grounded.position)

    def test_elapsed_time_can_change_which_flight_is_nearest(self) -> None:
        approaching = Flight(
            callsign="INBND1",
            position=Coordinates(47.70, -122.305),
            speed_knots=600.0,
            heading_degrees=180.0,
            seen_seconds_ago=1,
        )
        loitering = Flight(
            callsign="HOLD01",
            position=Coordinates(47.65, -122.305),
            seen_seconds_ago=1,
        )
        flights = [approaching, loitering]

        immediate = nearest_flight(flights, self.origin)
        later = nearest_flight(flights, self.origin, elapsed_seconds=40.0)

        assert immediate is not None and later is not None
        self.assertEqual(immediate.flight.callsign, "HOLD01")
        self.assertEqual(later.flight.callsign, "INBND1")

    def test_flights_age_out_as_time_passes_between_polls(self) -> None:
        flights = [
            Flight(callsign="AGING1", position=Coordinates(47.62, -122.305), seen_seconds_ago=55)
        ]

        self.assertIsNotNone(nearest_flight(flights, self.origin, maximum_seen_seconds=60))
        self.assertIsNone(
            nearest_flight(
                flights,
                self.origin,
                maximum_seen_seconds=60,
                elapsed_seconds=10.0,
            )
        )

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
