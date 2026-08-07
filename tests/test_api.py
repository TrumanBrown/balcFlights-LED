import json
import unittest
from pathlib import Path

from balc_flights_led.api import FlightApiContractError, parse_flight_feed

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flights.json"


class FlightApiTests(unittest.TestCase):
    def test_parses_documented_v1_shape_and_rejects_missing_position(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        feed = parse_flight_feed(payload)

        self.assertEqual(feed.api_version, "1.1")
        self.assertEqual(feed.status, "ok")
        self.assertEqual(feed.declared_count, 3)
        self.assertEqual(feed.rejected_flights, 1)
        self.assertEqual(len(feed.flights), 2)
        self.assertEqual(feed.flights[0].label, "ASA123")
        self.assertEqual(feed.flights[0].altitude_feet, 12000)
        self.assertEqual(feed.flights[1].label, "N456XY")
        self.assertIsNone(feed.flights[1].altitude_feet)

    def test_parses_the_projected_position(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        projection = parse_flight_feed(payload).flights[0].projection

        assert projection is not None
        self.assertEqual(projection.position.latitude, 47.624)
        self.assertEqual(projection.seconds, 1.0)
        self.assertFalse(projection.capped)
        self.assertEqual(projection.method, "constant-speed-heading")

    def test_flights_without_a_projection_still_parse(self) -> None:
        feed = parse_flight_feed(
            {
                "apiVersion": "1.1",
                "status": "ok",
                "flights": [
                    {
                        "identifiers": {"callsign": "NOPROJ"},
                        "position": {"latitude": 47.6, "longitude": -122.3, "projected": None},
                    }
                ],
            }
        )

        self.assertIsNone(feed.flights[0].projection)

    def test_degraded_empty_feed_remains_explicit(self) -> None:
        feed = parse_flight_feed(
            {
                "apiVersion": "1.0",
                "status": "degraded",
                "generatedAt": "2026-07-23T18:30:00.000Z",
                "source": "fallback-empty",
                "warnings": ["No upstream source was usable."],
                "count": 0,
                "flights": [],
            }
        )

        self.assertTrue(feed.is_degraded)
        self.assertEqual(feed.warnings, ("No upstream source was usable.",))
        self.assertEqual(feed.flights, ())

    def test_control_characters_never_leave_the_parser(self) -> None:
        feed = parse_flight_feed(
            {
                "apiVersion": "1.1",
                "status": "degraded",
                "source": "up\x1b[2Jstream",
                "warnings": ["clear\x1b[2J", 42],
                "flights": [
                    {
                        "identifiers": {"callsign": "ASA\x1b[31m123\n"},
                        "position": {"latitude": 47.6, "longitude": -122.3},
                    }
                ],
            }
        )

        # These strings reach the log and the terminal, so escapes must not survive.
        self.assertEqual(feed.flights[0].label, "ASA[31M123")
        self.assertEqual(feed.source, "up[2Jstream")
        self.assertEqual(feed.warnings, ("clear[2J",))

    def test_rejects_unknown_major_api_version(self) -> None:
        with self.assertRaisesRegex(FlightApiContractError, "unsupported.*version"):
            parse_flight_feed(
                {
                    "apiVersion": "2.0",
                    "status": "ok",
                    "flights": [],
                }
            )

    def test_requires_flights_array(self) -> None:
        with self.assertRaisesRegex(FlightApiContractError, "flights"):
            parse_flight_feed(
                {
                    "apiVersion": "1.0",
                    "status": "ok",
                    "flights": None,
                }
            )


if __name__ == "__main__":
    unittest.main()
