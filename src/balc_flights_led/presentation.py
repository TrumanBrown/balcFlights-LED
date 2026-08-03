from __future__ import annotations

import string
from dataclasses import dataclass

from .models import NearestFlight

# Each repeat emits a distance frame and an identity frame, so at the default
# display.page_seconds this holds the headline for about 12 seconds.
DEFAULT_HEADLINE_REPEATS = 3

COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True, slots=True)
class DisplayPage:
    """A static frame held for display.page_seconds.

    The callsign in `text` is always drawn. Whichever indicator field is set is
    drawn in the columns the callsign leaves free.
    """

    text: str
    bearing_degrees: float | None = None
    trend: int | None = None
    proximity: float | None = None
    stale: bool = False
    overhead: bool = False

    @property
    def self_timed(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class MarqueePage:
    """A detail line scrolled once across the full matrix width."""

    text: str
    stale: bool = False

    @property
    def self_timed(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ArrivalAnimation:
    """Plane sprite fly-through played once when the nearest aircraft changes."""

    text: str
    bearing_degrees: float | None = None
    overhead: bool = False

    @property
    def self_timed(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class IdleAnimation:
    """Drifting dots shown while no aircraft qualifies."""

    seconds: float = 4.0

    @property
    def self_timed(self) -> bool:
        return True


DisplayItem = DisplayPage | MarqueePage | ArrivalAnimation | IdleAnimation


def flight_pages(
    nearest: NearestFlight,
    *,
    stale: bool = False,
    overhead: bool = False,
    proximity: float | None = None,
    headline_repeats: int = DEFAULT_HEADLINE_REPEATS,
) -> tuple[DisplayItem, ...]:
    label = _matrix_text(nearest.flight.label)
    common = {
        "text": label,
        "proximity": proximity,
        "stale": stale,
        "overhead": overhead,
    }
    frames = (
        DisplayPage(bearing_degrees=nearest.bearing_degrees, **common),
        DisplayPage(trend=trend_value(nearest.flight.vertical_rate_fpm), **common),
    )
    return (*frames * max(1, headline_repeats), MarqueePage(detail_line(nearest), stale=stale))


def arrival_intro(nearest: NearestFlight, *, overhead: bool = False) -> tuple[DisplayItem, ...]:
    return (
        ArrivalAnimation(
            text=_matrix_text(nearest.flight.label),
            bearing_degrees=nearest.bearing_degrees,
            overhead=overhead,
        ),
    )


def status_pages(message: str) -> tuple[DisplayItem, ...]:
    return (DisplayPage(text=_matrix_text(message)),)


def idle_pages(message: str, *, seconds: float = 4.0) -> tuple[DisplayItem, ...]:
    return (DisplayPage(text=_matrix_text(message)), IdleAnimation(seconds=seconds))


def detail_line(nearest: NearestFlight) -> str:
    flight = nearest.flight
    parts = [flight.label]
    if flight.aircraft_type:
        parts.append(flight.aircraft_type)
    parts.append(_distance_text(nearest.distance_nautical_miles))
    parts.append(compass_point(nearest.bearing_degrees))
    parts.append(_altitude_text(flight.altitude_feet))
    parts.append(_trend_text(flight.vertical_rate_fpm))
    if flight.speed_knots is not None:
        parts.append(f"{round(flight.speed_knots):d}KT")
    return _matrix_text(" ".join(parts))


def console_summary(nearest: NearestFlight, *, stale: bool = False) -> str:
    flight = nearest.flight
    freshness = "stale" if stale else "fresh"
    altitude = (
        f"{flight.altitude_feet:,} ft" if flight.altitude_feet is not None else "unknown altitude"
    )
    speed = f"{flight.speed_knots:.0f} kt" if flight.speed_knots is not None else "unknown speed"
    return (
        f"{flight.label}: {nearest.distance_nautical_miles:.2f} NM away at "
        f"bearing {nearest.bearing_degrees:.0f} deg, {altitude}, {speed} ({freshness})"
    )


def compass_point(bearing_degrees: float) -> str:
    index = int((bearing_degrees % 360) / 45 + 0.5) % 8
    return COMPASS_POINTS[index]


def trend_value(vertical_rate_fpm: int | None) -> int:
    if vertical_rate_fpm is None or abs(vertical_rate_fpm) < 100:
        return 0
    return 1 if vertical_rate_fpm > 0 else -1


def _distance_text(distance_nautical_miles: float) -> str:
    if distance_nautical_miles < 10:
        return f"{distance_nautical_miles:.1f}NM"
    return f"{round(distance_nautical_miles):d}NM"


def _altitude_text(altitude_feet: int | None) -> str:
    if altitude_feet is None:
        return "ALT?"
    return f"{altitude_feet:d}FT"


def _trend_text(vertical_rate_fpm: int | None) -> str:
    return {1: "CLB", 0: "LVL", -1: "DES"}[trend_value(vertical_rate_fpm)]


def _matrix_text(value: str) -> str:
    allowed = set(string.ascii_uppercase + string.digits + ".-? ")
    normalized = "".join(character for character in value.upper() if character in allowed)
    return normalized.strip() or "UNKNOWN"
