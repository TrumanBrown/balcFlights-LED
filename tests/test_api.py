import json
import unittest
from pathlib import Path

from balc_flights_led.api import FlightApiContractError, parse_flight_feed

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flights.json"


class FlightApiTests(unittest.TestCase):
    def test_parses_documented_v1_shape_and_rejects_missing_position(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

        feed = parse_flight_feed(payload)

        self.assertEqual(feed.api_version, "1.0")
        self.assertEqual(feed.status, "ok")
        self.assertEqual(feed.declared_count, 3)
        self.assertEqual(feed.rejected_flights, 1)
        self.assertEqual(len(feed.flights), 2)
        self.assertEqual(feed.flights[0].label, "ASA123")
        self.assertEqual(feed.flights[0].altitude_feet, 12000)
        self.assertEqual(feed.flights[1].label, "N456XY")
        self.assertIsNone(feed.flights[1].altitude_feet)

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
