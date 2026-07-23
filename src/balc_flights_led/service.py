from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from .api import FlightApiClient, FlightApiError, FlightFeed
from .config import Settings
from .display import PageRenderer
from .models import NearestFlight
from .presentation import DisplayPage, console_summary, flight_pages, status_pages
from .selection import bounds_around, nearest_flight

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MonitorState:
    kind: str
    pages: tuple[DisplayPage, ...]
    summary: str
    source: str | None = None
    nearest: NearestFlight | None = None
    stale: bool = False


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

        selected = nearest_flight(
            feed.flights,
            self._settings.location,
            maximum_seen_seconds=self._settings.api.maximum_seen_seconds,
        )
        if selected is not None:
            self._remember(selected, feed)
            return self._flight_state(selected, feed.source, stale=feed.is_degraded)

        if feed.is_degraded:
            warning = "; ".join(feed.warnings) or "degraded flight data"
            return self._fallback_state("degraded", "DATA?", warning)

        return MonitorState(
            kind="empty",
            pages=status_pages("NO FLT"),
            summary=(
                "No eligible airborne flights in the "
                f"{self._settings.search_radius_nautical_miles:g} NM "
                f"search box (source={feed.source}, rejected={feed.rejected_flights})"
            ),
            source=feed.source,
        )

    def _remember(self, nearest: NearestFlight, feed: FlightFeed) -> None:
        self._last_nearest = nearest
        self._last_source = feed.source
        self._last_success_at = self._clock()

    def _flight_state(
        self,
        nearest: NearestFlight,
        source: str,
        *,
        stale: bool,
    ) -> MonitorState:
        return MonitorState(
            kind="flight",
            pages=flight_pages(nearest, stale=stale),
            summary=f"{console_summary(nearest, stale=stale)}; source={source}",
            source=source,
            nearest=nearest,
            stale=stale,
        )

    def _fallback_state(self, kind: str, matrix_message: str, reason: str) -> MonitorState:
        if self._last_nearest is not None and self._last_success_at is not None:
            age_seconds = self._clock() - self._last_success_at
            if age_seconds <= self._settings.api.last_known_ttl_seconds:
                state = self._flight_state(
                    self._last_nearest,
                    self._last_source or "last-known",
                    stale=True,
                )
                return MonitorState(
                    kind="stale",
                    pages=state.pages,
                    summary=f"{state.summary}; age={age_seconds:.0f}s; reason={reason}",
                    source=state.source,
                    nearest=state.nearest,
                    stale=True,
                )

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
    page_index = 0
    next_refresh_at = clock() + settings.api.refresh_seconds

    while True:
        renderer.render(state.pages[page_index % len(state.pages)])
        page_index += 1

        remaining = next_refresh_at - clock()
        if remaining > 0:
            sleeper(min(settings.display.page_seconds, remaining))

        if clock() >= next_refresh_at:
            state = monitor.refresh()
            LOGGER.info(state.summary)
            page_index = 0
            next_refresh_at = clock() + settings.api.refresh_seconds
