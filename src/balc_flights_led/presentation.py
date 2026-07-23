from __future__ import annotations

import string
from dataclasses import dataclass

from .models import NearestFlight


@dataclass(frozen=True, slots=True)
class DisplayPage:
    text: str
    bearing_degrees: float | None = None
    stale: bool = False


def flight_pages(nearest: NearestFlight, *, stale: bool = False) -> tuple[DisplayPage, ...]:
    flight = nearest.flight
    pages = [
        DisplayPage(
            text=_matrix_text(flight.label),
            bearing_degrees=nearest.bearing_degrees,
            stale=stale,
        ),
        DisplayPage(text=_distance_text(nearest.distance_nautical_miles), stale=stale),
        DisplayPage(
            text=_altitude_text(flight.altitude_feet, flight.vertical_rate_fpm),
            stale=stale,
        ),
    ]
    if flight.speed_knots is not None:
        pages.append(DisplayPage(text=f"{round(flight.speed_knots):d}KT", stale=stale))
    return tuple(pages)


def status_pages(message: str) -> tuple[DisplayPage, ...]:
    return (DisplayPage(text=_matrix_text(message)),)


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


def _distance_text(distance_nautical_miles: float) -> str:
    if distance_nautical_miles < 10:
        return f"{distance_nautical_miles:.1f}NM"
    return f"{round(distance_nautical_miles):d}NM"


def _altitude_text(altitude_feet: int | None, vertical_rate_fpm: int | None) -> str:
    if altitude_feet is None:
        return "ALT?"

    if abs(altitude_feet) >= 10_000:
        altitude = f"A{round(altitude_feet / 1000):d}K"
    else:
        altitude = f"A{round(altitude_feet / 100):d}H"

    if vertical_rate_fpm is None or abs(vertical_rate_fpm) < 100:
        trend = "="
    else:
        trend = "+" if vertical_rate_fpm > 0 else "-"
    return f"{altitude}{trend}"


def _matrix_text(value: str) -> str:
    allowed = set(string.ascii_uppercase + string.digits + "-? ")
    normalized = "".join(character for character in value.upper() if character in allowed)
    return normalized.strip() or "UNKNOWN"
