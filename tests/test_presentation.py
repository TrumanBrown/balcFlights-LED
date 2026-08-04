import unittest

from balc_flights_led.models import Coordinates, Flight, NearestFlight
from balc_flights_led.presentation import (
    OVERHEAD_BLINK_SECONDS,
    ArrivalAnimation,
    IdleAnimation,
    MarqueePage,
    arrival_intro,
    compass_point,
    console_summary,
    detail_line,
    flight_pages,
    idle_pages,
    status_pages,
)


class PresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nearest = NearestFlight(
            flight=Flight(
                position=Coordinates(47.625, -122.305),
                callsign="asa123",
                aircraft_type="B739",
                altitude_feet=12_000,
                speed_knots=229.6,
                vertical_rate_fpm=-500,
            ),
            distance_nautical_miles=0.45,
            bearing_degrees=359.7,
        )

    def test_every_headline_frame_keeps_the_callsign_and_bearing(self) -> None:
        pages = flight_pages(
            self.nearest,
            overhead=True,
            proximity=0.8,
            headline_repeats=3,
        )

        headline = pages[:3]
        self.assertEqual([page.text for page in headline], ["ASA123"] * 3)
        self.assertTrue(all(page.overhead for page in headline))
        self.assertTrue(all(page.proximity == 0.8 for page in headline))
        self.assertFalse(any(page.self_timed for page in headline))

        # The arrow is permanent, so no frame ever drops the bearing.
        self.assertTrue(all(page.bearing_degrees == 359.7 for page in headline))

        marquee = pages[-1]
        self.assertIsInstance(marquee, MarqueePage)
        self.assertTrue(marquee.self_timed)
        self.assertEqual(marquee.text, "ASA123 B739 0.5NM N 12000FT DES 230KT")

    def test_overhead_blinks_the_arrow_without_changing_the_headline_dwell(self) -> None:
        pages = flight_pages(
            self.nearest,
            overhead=True,
            proximity=0.8,
            headline_repeats=2,
            page_seconds=2.0,
        )

        headline = pages[:-1]
        self.assertEqual([page.text for page in headline], ["ASA123"] * len(headline))
        self.assertTrue(all(page.bearing_degrees == 359.7 for page in headline))

        visibility = [page.arrow_visible for page in headline]
        self.assertEqual(visibility, [index % 2 == 0 for index in range(len(headline))])

        # Blink frames are held briefly, but the headline still occupies the same time.
        holds = [page.hold_seconds for page in headline]
        self.assertTrue(all(hold == OVERHEAD_BLINK_SECONDS for hold in holds))
        self.assertAlmostEqual(sum(holds), 2 * 2.0)

    def test_detail_line_degrades_when_fields_are_missing(self) -> None:
        nearest = NearestFlight(
            flight=Flight(position=Coordinates(47.7, -122.3), registration="N123XY"),
            distance_nautical_miles=15.2,
            bearing_degrees=135.0,
        )

        self.assertEqual(detail_line(nearest), "N123XY 15NM SE ALT? LVL")

    def test_marks_every_page_when_last_known_data_is_stale(self) -> None:
        pages = flight_pages(self.nearest, stale=True)

        self.assertTrue(all(page.stale for page in pages))

    def test_arrival_intro_is_a_single_self_timed_animation(self) -> None:
        intro = arrival_intro(self.nearest, overhead=True)

        self.assertEqual(len(intro), 1)
        self.assertIsInstance(intro[0], ArrivalAnimation)
        self.assertEqual(intro[0].text, "ASA123")
        self.assertTrue(intro[0].overhead)
        self.assertTrue(intro[0].self_timed)

    def test_idle_pages_alternate_text_and_animation(self) -> None:
        pages = idle_pages("no flt", seconds=4.0)

        self.assertEqual(pages[0].text, "NO FLT")
        self.assertIsInstance(pages[1], IdleAnimation)

    def test_compass_point_wraps_around_north(self) -> None:
        self.assertEqual(compass_point(359.7), "N")
        self.assertEqual(compass_point(46.0), "NE")
        self.assertEqual(compass_point(200.0), "S")

    def test_console_summary_reports_distance(self) -> None:
        self.assertIn("0.45 NM", console_summary(self.nearest))

    def test_status_text_is_ascii_and_normalized(self) -> None:
        self.assertEqual(status_pages("no flights!")[0].text, "NO FLIGHTS")


if __name__ == "__main__":
    unittest.main()
