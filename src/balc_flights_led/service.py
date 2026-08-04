from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from .api import FlightApiClient, FlightApiError
from .config import Settings
from .display import PageRenderer
from .models import Flight, NearestFlight
from .presentation import (
    DisplayItem,
    arrival_intro,
    console_summary,
    flight_pages,
    idle_pages,
    status_pages,
)
from .selection import (
    bounds_around,
    distance_nautical_miles,
    estimated_position,
    initial_bearing_degrees,
    nearest_flight,
)

LOGGER = logging.getLogger(__name__)


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
        bounds = bounds_around(
            self._settings.location,
            self._settings.search_radius_nautical_miles,
        )
        try:
            feed = self._client.fetch(bounds)
        except FlightApiError as error:
            LOGGER.warning("Flight API unavailable: %s", error)
            return self._fallback_state("offline", "OFFLINE", str(error))

        self._cached_flights = feed.flights
        self._cached_degraded = feed.is_degraded
        self._cached_warnings = feed.warnings
        self._cached_rejected = feed.rejected_flights
        self._last_source = feed.source
        self._fetched_at = self._clock()
        return self._select(0.0)

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
            return self._flight_state(selected, source, stale=self._cached_degraded)

        if self._cached_degraded:
            warning = "; ".join(self._cached_warnings) or "degraded flight data"
            return self._fallback_state("degraded", "DATA?", warning)

        self._displayed_label = None
        return MonitorState(
            kind="empty",
            pages=idle_pages("NO FLT", seconds=self._settings.display.page_seconds * 2),
            summary=(
                "No eligible airborne flights in the "
                f"{self._settings.search_radius_nautical_miles:g} NM "
                f"search box (source={source}, rejected={self._cached_rejected})"
            ),
            source=source,
        )

    def _flight_state(
        self,
        nearest: NearestFlight,
        source: str,
        *,
        stale: bool,
    ) -> MonitorState:
        overhead = nearest.distance_nautical_miles <= self._settings.overhead_radius_nautical_miles
        proximity = max(
            0.0,
            1.0 - nearest.distance_nautical_miles / self._settings.search_radius_nautical_miles,
        )
        # The intro only fires when the aircraft on screen actually changes.
        is_new = nearest.flight.label != self._displayed_label
        self._displayed_label = nearest.flight.label
        intro = (
            arrival_intro(nearest, overhead=overhead)
            if is_new and self._settings.display.animations
            else ()
        )
        marker = " OVERHEAD" if overhead else ""
        return MonitorState(
            kind="flight",
            pages=flight_pages(nearest, stale=stale, overhead=overhead, proximity=proximity),
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


def run_forever(
    monitor: FlightMonitor,
    renderer: PageRenderer,
    settings: Settings,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    state = monitor.refresh()
    LOGGER.info(state.summary)
    pending_intro = list(state.intro)
    page_index = 0
    next_refresh_at = clock() + settings.api.refresh_seconds

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

        remaining = next_refresh_at - clock()
        if not item.self_timed and remaining > 0:
            sleeper(min(settings.display.page_seconds, remaining))

        if clock() >= next_refresh_at:
            state = monitor.refresh()
            LOGGER.info(state.summary)
            pending_intro = list(state.intro)
            page_index = 0
            next_refresh_at = clock() + settings.api.refresh_seconds
