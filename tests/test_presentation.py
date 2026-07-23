import unittest

from balc_flights_led.models import Coordinates, Flight, NearestFlight
from balc_flights_led.presentation import console_summary, flight_pages, status_pages


class PresentationTests(unittest.TestCase):
    def test_builds_compact_aviation_pages(self) -> None:
        nearest = NearestFlight(
            flight=Flight(
                position=Coordinates(47.625, -122.305),
                callsign="asa123",
                altitude_feet=12_000,
                speed_knots=229.6,
                vertical_rate_fpm=-500,
            ),
            distance_nautical_miles=0.45,
            bearing_degrees=359.7,
        )

        pages = flight_pages(nearest)

        self.assertEqual([page.text for page in pages], ["ASA123", "0.5NM", "A12K-", "230KT"])
        self.assertAlmostEqual(pages[0].bearing_degrees or 0, 359.7)
        self.assertFalse(any(page.stale for page in pages))
        self.assertIn("0.45 NM", console_summary(nearest))

    def test_marks_every_page_when_last_known_data_is_stale(self) -> None:
        nearest = NearestFlight(
            flight=Flight(position=Coordinates(47.7, -122.3), registration="N123XY"),
            distance_nautical_miles=5.0,
            bearing_degrees=20,
        )

        pages = flight_pages(nearest, stale=True)

        self.assertTrue(all(page.stale for page in pages))
        self.assertEqual(pages[2].text, "ALT?")

    def test_status_text_is_ascii_and_normalized(self) -> None:
        self.assertEqual(status_pages("no flights!")[0].text, "NO FLIGHTS")


if __name__ == "__main__":
    unittest.main()
