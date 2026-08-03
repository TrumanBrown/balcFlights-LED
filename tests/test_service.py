import unittest

from balc_flights_led.api import FlightApiError, FlightFeed
from balc_flights_led.config import load_settings
from balc_flights_led.models import Coordinates, Flight
from balc_flights_led.service import FlightMonitor


class FakeClient:
    def __init__(self, responses: list[FlightFeed | FlightApiError]) -> None:
        self.responses = responses

    def fetch(self, _bounds):
        response = self.responses.pop(0)
        if isinstance(response, FlightApiError):
            raise response
        return response


def feed(*flights: Flight, status: str = "ok", source: str = "test") -> FlightFeed:
    return FlightFeed(
        api_version="1.0",
        status=status,
        generated_at="2026-07-23T18:30:00.000Z",
        source=source,
        warnings=("upstream unavailable",) if status == "degraded" else (),
        flights=flights,
        declared_count=len(flights),
    )


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.clock = lambda: self.now
        self.settings = load_settings(environ={})
        self.flight = Flight(
            position=Coordinates(47.625, -122.305),
            callsign="ASA123",
            seen_seconds_ago=1,
        )

    def test_fresh_flight_is_selected_and_cached(self) -> None:
        monitor = FlightMonitor(
            self.settings,
            FakeClient([feed(self.flight)]),
            clock=self.clock,
        )

        state = monitor.refresh()

        self.assertEqual(state.kind, "flight")
        self.assertFalse(state.stale)
        self.assertEqual(state.nearest.flight.callsign if state.nearest else None, "ASA123")

    def test_close_aircraft_is_flagged_overhead(self) -> None:
        monitor = FlightMonitor(
            self.settings,
            FakeClient([feed(self.flight)]),
            clock=self.clock,
        )

        state = monitor.refresh()

        self.assertTrue(state.overhead)
        self.assertIn("OVERHEAD", state.summary)

    def test_arrival_animation_plays_only_when_the_aircraft_changes(self) -> None:
        other = Flight(
            position=Coordinates(47.63, -122.305),
            callsign="DAL456",
            seen_seconds_ago=1,
        )
        monitor = FlightMonitor(
            self.settings,
            FakeClient([feed(self.flight), feed(self.flight), feed(other)]),
            clock=self.clock,
        )

        first = monitor.refresh()
        repeat = monitor.refresh()
        changed = monitor.refresh()

        self.assertEqual(len(first.intro), 1)
        self.assertEqual(repeat.intro, ())
        self.assertEqual(len(changed.intro), 1)
        self.assertEqual(changed.intro[0].text, "DAL456")

    def test_animations_can_be_disabled(self) -> None:
        settings = load_settings(environ={"BFL_ANIMATIONS": "false"})
        monitor = FlightMonitor(
            settings,
            FakeClient([feed(self.flight)]),
            clock=self.clock,
        )

        self.assertEqual(monitor.refresh().intro, ())

    def test_degraded_empty_feed_uses_recent_last_known_flight(self) -> None:
        monitor = FlightMonitor(
            self.settings,
            FakeClient([feed(self.flight), feed(status="degraded")]),
            clock=self.clock,
        )
        monitor.refresh()
        self.now += 30

        state = monitor.refresh()

        self.assertEqual(state.kind, "stale")
        self.assertTrue(state.stale)
        self.assertTrue(all(page.stale for page in state.pages))
        self.assertIn("age=30s", state.summary)

    def test_expired_last_known_flight_is_not_displayed(self) -> None:
        monitor = FlightMonitor(
            self.settings,
            FakeClient([feed(self.flight), feed(status="degraded")]),
            clock=self.clock,
        )
        monitor.refresh()
        self.now += self.settings.api.last_known_ttl_seconds + 1

        state = monitor.refresh()

        self.assertEqual(state.kind, "degraded")
        self.assertEqual(state.pages[0].text, "DATA?")

    def test_network_error_without_cache_is_offline(self) -> None:
        monitor = FlightMonitor(
            self.settings,
            FakeClient([FlightApiError("timeout")]),
            clock=self.clock,
        )

        state = monitor.refresh()

        self.assertEqual(state.kind, "offline")
        self.assertEqual(state.pages[0].text, "OFFLINE")

    def test_fresh_empty_feed_means_no_eligible_flights(self) -> None:
        monitor = FlightMonitor(
            self.settings,
            FakeClient([feed()]),
            clock=self.clock,
        )

        state = monitor.refresh()

        self.assertEqual(state.kind, "empty")
        self.assertEqual(state.pages[0].text, "NO FLT")


if __name__ == "__main__":
    unittest.main()
