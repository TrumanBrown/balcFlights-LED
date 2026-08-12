import threading
import unittest
from dataclasses import replace
from pathlib import Path

from balc_flights_led.api import FlightApiError, FlightFeed
from balc_flights_led.config import load_settings
from balc_flights_led.models import Coordinates, Flight
from balc_flights_led.presentation import DisplayPage, RadarPage
from balc_flights_led.service import FlightMonitor, run_forever


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
        # An absent path, so the suite tests the defaults rather than whatever
        # balc.local.toml happens to say on the machine running it.
        self.settings = load_settings(Path("balc.absent.toml"), environ={})
        self.flight = Flight(
            position=Coordinates(47.625, -122.305),
            callsign="ASA123",
            seen_seconds_ago=1,
        )

    def test_reprojection_tracks_the_aircraft_between_polls(self) -> None:
        inbound = Flight(
            position=Coordinates(47.70, -122.305),
            callsign="INBND1",
            speed_knots=600.0,
            heading_degrees=180.0,
            seen_seconds_ago=1,
        )
        monitor = FlightMonitor(self.settings, FakeClient([feed(inbound)]), clock=self.clock)

        first = monitor.refresh()
        self.now += 15.0
        later = monitor.reproject()

        assert first.nearest is not None
        assert later is not None and later.nearest is not None
        self.assertLess(
            later.nearest.distance_nautical_miles,
            first.nearest.distance_nautical_miles,
        )

    def test_reprojection_before_any_fetch_returns_nothing(self) -> None:
        monitor = FlightMonitor(self.settings, FakeClient([]), clock=self.clock)

        self.assertIsNone(monitor.reproject())

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


class RadarLayoutTests(unittest.TestCase):
    """A HUB75 panel plots the whole picture; the MAX7219 chain keeps the single pick."""

    def setUp(self) -> None:
        self.now = 100.0
        self.clock = lambda: self.now
        self.settings = load_settings(Path("balc.absent.toml"), environ={})
        self.near = Flight(
            position=Coordinates(47.625, -122.305),
            callsign="ASA123",
            vertical_rate_fpm=1200,
            seen_seconds_ago=1,
        )
        self.far = Flight(
            position=Coordinates(47.70, -122.305),
            callsign="DAL88",
            vertical_rate_fpm=-900,
            seen_seconds_ago=1,
        )

    def hub75(self, **display):
        overrides = {"panel": "hub75", "radar": True, **display}
        return replace(self.settings, display=replace(self.settings.display, **overrides))

    def monitor(self, settings, *flights) -> FlightMonitor:
        return FlightMonitor(settings, FakeClient([feed(*flights)]), clock=self.clock)

    def test_every_flight_in_range_reaches_the_radar(self) -> None:
        state = self.monitor(self.hub75(), self.near, self.far).refresh()

        page = state.pages[0]
        self.assertIsInstance(page, RadarPage)
        self.assertEqual({track.label for track in page.tracks}, {"ASA123", "DAL88"})
        self.assertEqual([track.label for track in page.tracks if track.nearest], ["ASA123"])

    def test_vertical_rate_reaches_the_radar_as_a_trend(self) -> None:
        state = self.monitor(self.hub75(), self.near, self.far).refresh()

        trends = {track.label: track.trend for track in state.pages[0].tracks}
        self.assertEqual(trends, {"ASA123": 1, "DAL88": -1})

    def test_the_arrival_transition_wipes_the_dial_in(self) -> None:
        state = self.monitor(self.hub75(), self.near).refresh()

        self.assertEqual(len(state.intro), 1)
        # The sprite hands over to the radar, not to the callsign page.
        self.assertIs(state.intro[0].page, state.pages[0])

    def test_the_max7219_arrival_carries_no_radar_page(self) -> None:
        state = self.monitor(self.settings, self.near).refresh()

        self.assertIsNone(state.intro[0].page)

    def test_an_empty_feed_still_shows_the_dial(self) -> None:
        state = self.monitor(self.hub75()).refresh()

        self.assertEqual(state.kind, "empty")
        self.assertIsInstance(state.pages[0], RadarPage)
        self.assertEqual(state.pages[0].tracks, ())

    def test_disabling_the_radar_restores_the_paged_layout(self) -> None:
        state = self.monitor(self.hub75(radar=False), self.near).refresh()

        self.assertIsInstance(state.pages[0], DisplayPage)

    def test_the_max7219_chain_is_unaffected(self) -> None:
        state = self.monitor(self.settings, self.near).refresh()

        self.assertIsInstance(state.pages[0], DisplayPage)

    def test_only_the_nearest_contacts_are_plotted(self) -> None:
        crowd = [
            Flight(
                position=Coordinates(47.625 + index * 0.01, -122.305),
                callsign=f"FLT{index:03d}",
                seen_seconds_ago=1,
            )
            for index in range(10)
        ]

        state = self.monitor(self.hub75(radar_contacts=4), *crowd).refresh()

        page = state.pages[0]
        self.assertEqual(len(page.tracks), 4)
        # Nearest first, so the four kept are the four closest.
        distances = [track.distance_nautical_miles for track in page.tracks]
        self.assertEqual(distances, sorted(distances))
        self.assertLess(max(distances), 3.0)

    def test_zero_contacts_means_no_limit(self) -> None:
        state = self.monitor(self.hub75(radar_contacts=0), self.near, self.far).refresh()

        self.assertEqual(len(state.pages[0].tracks), 2)

    def test_the_dial_covers_the_configured_radar_range(self) -> None:
        settings = self.hub75(radar_range_nautical_miles=3.0)

        state = self.monitor(settings, self.near, self.far).refresh()

        page = state.pages[0]
        self.assertEqual(page.range_nautical_miles, 3.0)
        # DAL88 is roughly 5 NM out, so the tighter dial drops it.
        self.assertEqual({track.label for track in page.tracks}, {"ASA123"})

    def test_the_radar_range_never_exceeds_what_was_fetched(self) -> None:
        settings = self.hub75(radar_range_nautical_miles=500.0)

        state = self.monitor(settings, self.near).refresh()

        self.assertEqual(
            state.pages[0].range_nautical_miles,
            settings.search_radius_nautical_miles,
        )

    def test_a_zero_range_follows_the_search_radius(self) -> None:
        settings = self.hub75(radar_range_nautical_miles=0.0)

        state = self.monitor(settings, self.near).refresh()

        self.assertEqual(
            state.pages[0].range_nautical_miles,
            settings.search_radius_nautical_miles,
        )


class LoopStopped(Exception):
    """Ends run_forever's infinite loop from inside the renderer."""


class GatedClient:
    """Holds the second fetch open until the display has proved it kept drawing."""

    def __init__(self, response: FlightFeed) -> None:
        self.response = response
        self.calls = 0
        self.gate = threading.Event()
        self.in_flight = threading.Event()

    def fetch(self, _bounds):
        self.calls += 1
        if self.calls == 1:
            return self.response
        self.in_flight.set()
        released = self.gate.wait(timeout=2)
        self.in_flight.clear()
        if not released:
            raise FlightApiError("the render loop never released the poll")
        return self.response


class GatedRenderer:
    def __init__(self, client: GatedClient) -> None:
        self.client = client
        self.frames = 0
        self.frames_during_poll = 0

    def render(self, _item) -> None:
        self.frames += 1
        if self.client.in_flight.is_set():
            self.frames_during_poll += 1
            if self.frames_during_poll >= 3:
                self.client.gate.set()
                raise LoopStopped
        if self.frames >= 60:
            raise LoopStopped

    def close(self) -> None:
        return None


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RunLoopTests(unittest.TestCase):
    """A poll must not stop the panel; that showed as the display freezing mid-sweep."""

    def test_the_display_keeps_drawing_while_a_poll_is_in_flight(self) -> None:
        settings = load_settings(Path("balc.absent.toml"), environ={})
        client = GatedClient(
            feed(
                Flight(
                    position=Coordinates(47.70, -122.305),
                    callsign="ASA123",
                    seen_seconds_ago=1,
                )
            )
        )
        renderer = GatedRenderer(client)
        clock = FakeClock()

        monitor = FlightMonitor(settings, client, clock=clock)
        with self.assertRaises(LoopStopped):
            run_forever(monitor, renderer, settings, clock=clock, sleeper=clock.advance)

        self.assertEqual(client.calls, 2)
        self.assertGreaterEqual(renderer.frames_during_poll, 3)


if __name__ == "__main__":
    unittest.main()
