import http.client
import io
import json
import unittest
from pathlib import Path
from urllib.request import Request

from balc_flights_led.api import (
    MAXIMUM_IDENTIFIER_LENGTH,
    MAXIMUM_WARNINGS,
    FlightApiClient,
    FlightApiContractError,
    FlightApiError,
    _HttpsOnlyRedirects,
    parse_flight_feed,
)
from balc_flights_led.models import BoundingBox

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flights.json"
BOUNDS = BoundingBox(47.0, -123.0, 48.0, -122.0)


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, url: str = "https://example.test/api") -> None:
        super().__init__(body)
        self._url = url

    def geturl(self) -> str:
        return self._url


def opener_returning(response: FakeResponse):
    return lambda _request, timeout: response


def opener_raising(error: Exception):
    def opener(_request, timeout):
        raise error

    return opener


def flight_payload(**overrides: object) -> dict[str, object]:
    flight: dict[str, object] = {
        "identifiers": {"callsign": "ASA123"},
        "position": {"latitude": 47.6, "longitude": -122.3},
    }
    for section, values in overrides.items():
        flight[section] = {**flight.get(section, {}), **values}
    return {"apiVersion": "1.1", "status": "ok", "flights": [flight]}


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

    def test_out_of_range_numbers_are_treated_as_missing(self) -> None:
        feed = parse_flight_feed(
            flight_payload(
                position={"altitudeFeet": 10**400},
                movement={
                    "speedKnots": 1e308,
                    "headingDegrees": 720,
                    "verticalRateFeetPerMinute": -(10**9),
                },
                signal={"seenSecondsAgo": -5},
            )
        )

        flight = feed.flights[0]
        self.assertIsNone(flight.altitude_feet)
        self.assertIsNone(flight.speed_knots)
        self.assertIsNone(flight.heading_degrees)
        self.assertIsNone(flight.vertical_rate_fpm)
        self.assertEqual(flight.seen_seconds_ago, 0.0)

    def test_oversized_strings_are_capped(self) -> None:
        payload = flight_payload(identifiers={"callsign": "A" * 4_000_000})
        payload["warnings"] = ["warning"] * 1000

        feed = parse_flight_feed(payload)

        self.assertEqual(len(feed.flights[0].label), MAXIMUM_IDENTIFIER_LENGTH)
        self.assertEqual(len(feed.warnings), MAXIMUM_WARNINGS)


class FlightApiClientTests(unittest.TestCase):
    def test_parses_a_response(self) -> None:
        body = FIXTURE_PATH.read_bytes()
        client = FlightApiClient(opener=opener_returning(FakeResponse(body)))

        self.assertEqual(len(client.fetch(BOUNDS).flights), 2)

    def test_a_response_that_left_https_is_rejected(self) -> None:
        body = FIXTURE_PATH.read_bytes()
        client = FlightApiClient(
            opener=opener_returning(FakeResponse(body, url="http://example.test/api"))
        )

        with self.assertRaisesRegex(FlightApiError, "HTTPS"):
            client.fetch(BOUNDS)

    def test_redirects_may_not_leave_https(self) -> None:
        handler = _HttpsOnlyRedirects()
        request = Request("https://example.test/api")

        for target in ("http://example.test/api", "file:///etc/passwd", "ftp://example.test/"):
            with self.subTest(target=target), self.assertRaisesRegex(FlightApiError, "HTTPS"):
                handler.redirect_request(request, None, 302, "Found", {}, target)

        followed = handler.redirect_request(
            request, None, 302, "Found", {}, "https://example.test/v2"
        )
        self.assertEqual(followed.full_url if followed else None, "https://example.test/v2")

    def test_protocol_errors_do_not_echo_server_bytes(self) -> None:
        client = FlightApiClient(opener=opener_raising(http.client.BadStatusLine("\x1b[2Jhostile")))

        with self.assertRaises(FlightApiError) as raised:
            client.fetch(BOUNDS)

        self.assertNotIn("\x1b", str(raised.exception))
        self.assertIn("BadStatusLine", str(raised.exception))

    def test_unparseable_bodies_are_contract_errors(self) -> None:
        for body in (
            b'{"count": ' + b"9" * 5000 + b"}",
            b"[" * 100_000,
            b"\xff\xfe",
        ):
            client = FlightApiClient(opener=opener_returning(FakeResponse(body)))
            with self.subTest(body=body[:12]), self.assertRaises(FlightApiContractError):
                client.fetch(BOUNDS)


if __name__ == "__main__":
    unittest.main()
