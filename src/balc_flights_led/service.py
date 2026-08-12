from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .api import FlightApiClient, FlightApiError, FlightFeed
from .config import Settings
from .display import PageRenderer
from .models import Flight, NearestFlight
from .presentation import (
    DisplayItem,
    DisplayPage,
    RadarPage,
    arrival_intro,
    console_summary,
    flight_pages,
    idle_pages,
    radar_idle_pages,
    radar_pages,
    status_pages,
)
from .selection import (
    bounds_around,
    distance_nautical_miles,
    estimated_position,
    flights_in_radius,
    initial_bearing_degrees,
    nearest_flight,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PollResult:
    """One completed API poll, produced away from the renderer."""

    fetched_at: float
    feed: FlightFeed | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MonitorState:
    kind: str
    pages: tuple[DisplayItem, ...]
    summary: str
    intro: tuple[DisplayItem, ...] = ()
    source: str | None = None
    nearest: NearestFlight | None = None
    stale: bool = False
    overhead: bool = False


class FlightMonitor:
    def __init__(
        self,
        settings: Settings,
        client: FlightApiClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock = clock
        self._last_nearest: NearestFlight | None = None
        self._last_source: str | None = None
        self._last_success_at: float | None = None
        self._displayed_label: str | None = None
        self._cached_flights: tuple[Flight, ...] = ()
        self._cached_degraded = False
        self._cached_warnings: tuple[str, ...] = ()
        self._cached_rejected = 0
        self._fetched_at: float | None = None

    def refresh(self) -> MonitorState:
        return self.apply(self.poll())

    def poll(self) -> PollResult:
        """Fetch the feed. Touches no monitor state, so it is safe off the render thread."""
        bounds = bounds_around(
            self._settings.location,
            self._settings.search_radius_nautical_miles,
        )
        try:
            feed = self._client.fetch(bounds)
        except FlightApiError as error:
            return PollResult(fetched_at=self._clock(), error=str(error))
        return PollResult(fetched_at=self._clock(), feed=feed)

    def apply(self, result: PollResult) -> MonitorState:
        """Fold a completed poll into the displayed state."""
        if result.feed is None:
            reason = result.error or "flight API unavailable"
            LOGGER.warning("Flight API unavailable: %s", reason)
            return self._fallback_state("offline", "OFFLINE", reason)

        self._cached_flights = result.feed.flights
        self._cached_degraded = result.feed.is_degraded
        self._cached_warnings = result.feed.warnings
        self._cached_rejected = result.feed.rejected_flights
        self._last_source = result.feed.source
        self._fetched_at = result.fetched_at
        return self._select(max(0.0, self._clock() - result.fetched_at))

    def reproject(self) -> MonitorState | None:
        """Recompute geometry from the cached feed without issuing a request."""
        if self._fetched_at is None:
            return None
        return self._select(self._clock() - self._fetched_at)

    def _select(self, elapsed_seconds: float) -> MonitorState:
        selected = nearest_flight(
            self._cached_flights,
            self._settings.location,
            maximum_seen_seconds=self._settings.api.maximum_seen_seconds,
            elapsed_seconds=elapsed_seconds,
        )
        source = self._last_source or "unknown"
        if selected is not None:
            self._last_nearest = selected
            self._last_success_at = self._fetched_at
            return self._flight_state(
                selected,
                source,
                stale=self._cached_degraded,
                tracked=self._tracked(elapsed_seconds),
            )

        if self._cached_degraded:
            warning = "; ".join(self._cached_warnings) or "degraded flight data"
            return self._fallback_state("degraded", "DATA?", warning)

        self._displayed_label = None
        return MonitorState(
            kind="empty",
            pages=self._idle_pages(),
            summary=(
                "No eligible airborne flights in the "
                f"{self._settings.search_radius_nautical_miles:g} NM "
                f"search box (source={source}, rejected={self._cached_rejected})"
            ),
            source=source,
        )

    @property
    def _radar_layout(self) -> bool:
        """The radar needs a panel with room for it; the MAX7219 chain has none."""
        return self._settings.display.panel == "hub75" and self._settings.display.radar

    @property
    def _radar_range(self) -> float:
        """How much sky the dial covers, never more than what was actually fetched."""
        configured = self._settings.display.radar_range_nautical_miles
        search = self._settings.search_radius_nautical_miles
        return min(configured, search) if configured > 0 else search

    def _tracked(self, elapsed_seconds: float) -> tuple[NearestFlight, ...]:
        if not self._radar_layout:
            return ()
        return flights_in_radius(
            self._cached_flights,
            self._settings.location,
            self._radar_range,
            maximum_seen_seconds=self._settings.api.maximum_seen_seconds,
            elapsed_seconds=elapsed_seconds,
        )

    def _idle_pages(self) -> tuple[DisplayItem, ...]:
        if self._radar_layout:
            return radar_idle_pages(
                "NO FLT",
                range_nautical_miles=self._radar_range,
                seconds=self._settings.display.page_seconds,
            )
        return idle_pages("NO FLT", seconds=self._settings.display.page_seconds * 2)

    def _flight_state(
        self,
        nearest: NearestFlight,
        source: str,
        *,
        stale: bool,
        tracked: tuple[NearestFlight, ...] = (),
    ) -> MonitorState:
        overhead = nearest.distance_nautical_miles <= self._settings.overhead_radius_nautical_miles
        proximity = max(
            0.0,
            1.0 - nearest.distance_nautical_miles / self._settings.search_radius_nautical_miles,
        )
        marker = " OVERHEAD" if overhead else ""
        pages: tuple[DisplayItem, ...]
        revealed: RadarPage | None = None
        if self._radar_layout:
            radar = radar_pages(
                nearest,
                tracked or (nearest,),
                range_nautical_miles=self._radar_range,
                limit=self._settings.display.radar_contacts,
                stale=stale,
                overhead=overhead,
                seconds=self._settings.display.page_seconds,
            )
            pages = radar
            # The sprite hands over to the dial rather than to a callsign page.
            revealed = radar[0]
        else:
            pages = flight_pages(
                nearest,
                stale=stale,
                overhead=overhead,
                proximity=proximity,
                page_seconds=self._settings.display.page_seconds,
            )

        # The intro only fires when the aircraft on screen actually changes.
        is_new = nearest.flight.label != self._displayed_label
        self._displayed_label = nearest.flight.label
        intro = (
            arrival_intro(nearest, overhead=overhead, page=revealed)
            if is_new and self._settings.display.animations
            else ()
        )
        return MonitorState(
            kind="flight",
            pages=pages,
            summary=f"{console_summary(nearest, stale=stale)}; source={source}{marker}",
            intro=intro,
            source=source,
            nearest=nearest,
            stale=stale,
            overhead=overhead,
        )

    def _reprojected(self, nearest: NearestFlight, elapsed_seconds: float) -> NearestFlight:
        position = estimated_position(nearest.flight, elapsed_seconds)
        return NearestFlight(
            flight=nearest.flight,
            distance_nautical_miles=distance_nautical_miles(self._settings.location, position),
            bearing_degrees=initial_bearing_degrees(self._settings.location, position),
        )

    def _fallback_state(self, kind: str, matrix_message: str, reason: str) -> MonitorState:
        if self._last_nearest is not None and self._last_success_at is not None:
            age_seconds = self._clock() - self._last_success_at
            if age_seconds <= self._settings.api.last_known_ttl_seconds:
                state = self._flight_state(
                    self._reprojected(self._last_nearest, age_seconds),
                    self._last_source or "last-known",
                    stale=True,
                )
                return MonitorState(
                    kind="stale",
                    pages=state.pages,
                    summary=f"{state.summary}; age={age_seconds:.0f}s; reason={reason}",
                    intro=state.intro,
                    source=state.source,
                    nearest=state.nearest,
                    stale=True,
                    overhead=state.overhead,
                )

        self._displayed_label = None
        return MonitorState(
            kind=kind,
            pages=status_pages(matrix_message),
            summary=f"Flight data unavailable: {reason}",
        )


class BackgroundPoller:
    """Runs the API fetch on its own thread so the panel never stops animating.

    An inline poll holds the last frame for as long as the request takes: most
    of a second on a healthy network, `api.timeout_seconds` on a stalled one,
    and longer still when name resolution hangs, which no socket timeout bounds.
    """

    def __init__(self, monitor: FlightMonitor) -> None:
        self._monitor = monitor
        self._lock = threading.Lock()
        self._result: PollResult | None = None
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Begin a poll, unless the previous one is still out."""
        if self.busy:
            return
        # Daemon, so a request wedged in the kernel cannot keep Ctrl+C waiting.
        self._thread = threading.Thread(target=self._poll, name="flight-poll", daemon=True)
        self._thread.start()

    def take(self) -> PollResult | None:
        """The completed poll, once, or None while one is still in flight."""
        with self._lock:
            result, self._result = self._result, None
        return result

    def _poll(self) -> None:
        result = self._monitor.poll()
        with self._lock:
            self._result = result


def run_forever(
    monitor: FlightMonitor,
    renderer: PageRenderer,
    settings: Settings,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    poller: BackgroundPoller | None = None,
) -> None:
    poller = poller if poller is not None else BackgroundPoller(monitor)
    # The first poll is inline; there is nothing to animate until it lands.
    state = monitor.refresh()
    LOGGER.info(state.summary)
    pending_intro = list(state.intro)
    page_index = 0
    next_poll_at = clock() + settings.api.refresh_seconds

    while True:
        if pending_intro:
            item = pending_intro.pop(0)
        else:
            # Re-derive positions from the cached feed so the arrow and distance
            # keep moving between polls instead of freezing for the interval.
            live = monitor.reproject()
            if live is not None:
                state = live
                if live.intro:
                    pending_intro = list(live.intro)
                    page_index = 0
                    continue
            item = state.pages[page_index % len(state.pages)]
            page_index += 1
        renderer.render(item)

        remaining = next_poll_at - clock()
        if not item.self_timed and remaining > 0:
            hold = item.hold_seconds if isinstance(item, DisplayPage) else None
            sleeper(min(hold or settings.display.page_seconds, remaining))

        if clock() >= next_poll_at:
            poller.start()
            next_poll_at = clock() + settings.api.refresh_seconds

        result = poller.take()
        if result is not None:
            state = monitor.apply(result)
            LOGGER.info(state.summary)
            pending_intro = list(state.intro)
            page_index = 0
