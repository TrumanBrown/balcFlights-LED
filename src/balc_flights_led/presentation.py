from __future__ import annotations

import string
from collections.abc import Sequence
from dataclasses import dataclass

from .models import NearestFlight

# The bearing arrow is now permanent, so every headline frame is identical and
# this simply holds the callsign for about 12 seconds at the default page time.
DEFAULT_HEADLINE_REPEATS = 6

# Overhead blinks the arrow rather than inverting its block: a lit 8x8 field
# overwhelms the glyph it is meant to qualify.
OVERHEAD_BLINK_SECONDS = 0.4

COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True, slots=True)
class DisplayPage:
    """A static frame held for display.page_seconds.

    The callsign in `text` is always drawn. Whichever indicator field is set is
    drawn in the columns the callsign leaves free.
    """

    text: str
    bearing_degrees: float | None = None
    proximity: float | None = None
    stale: bool = False
    overhead: bool = False
    arrow_visible: bool = True
    # Overrides display.page_seconds so a blink frame can be held briefly.
    hold_seconds: float | None = None

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
    # The frame wiped in behind the sprite. None means the callsign page.
    page: RadarPage | None = None

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


@dataclass(frozen=True, slots=True)
class RadarTrack:
    """One aircraft plotted on the radar."""

    label: str
    distance_nautical_miles: float
    bearing_degrees: float
    trend: int = 0
    nearest: bool = False


@dataclass(frozen=True, slots=True)
class RadarPage:
    """A PPI radar of every aircraft in range, over a detail block for the nearest.

    Self-timed because the sweep animates: the renderer holds it for `seconds`
    and the caller re-derives positions before handing over the next one.
    """

    range_nautical_miles: float
    tracks: tuple[RadarTrack, ...] = ()
    label: str = ""
    detail: tuple[str, ...] = ()
    distance_text: str = ""
    compass: str = ""
    trend: int = 0
    # Where the aircraft is pointing, which the radar's position cannot show.
    heading_degrees: float | None = None
    stale: bool = False
    overhead: bool = False
    seconds: float = 0.5

    @property
    def self_timed(self) -> bool:
        return True


DisplayItem = DisplayPage | MarqueePage | ArrivalAnimation | IdleAnimation | RadarPage


def flight_pages(
    nearest: NearestFlight,
    *,
    stale: bool = False,
    overhead: bool = False,
    proximity: float | None = None,
    headline_repeats: int = DEFAULT_HEADLINE_REPEATS,
    page_seconds: float = 2.0,
) -> tuple[DisplayItem, ...]:
    label = _matrix_text(nearest.flight.label)
    common = {
        "text": label,
        "proximity": proximity,
        "stale": stale,
        "overhead": overhead,
    }
    repeats = max(1, headline_repeats)
    if overhead:
        # Split each headline slot into blink frames so the total dwell is unchanged.
        per_slot = max(2, round(page_seconds / OVERHEAD_BLINK_SECONDS))
        frames = tuple(
            DisplayPage(
                bearing_degrees=nearest.bearing_degrees,
                arrow_visible=index % 2 == 0,
                hold_seconds=OVERHEAD_BLINK_SECONDS,
                **common,
            )
            for index in range(repeats * per_slot)
        )
    else:
        frames = (DisplayPage(bearing_degrees=nearest.bearing_degrees, **common),) * repeats
    return (*frames, MarqueePage(detail_line(nearest), stale=stale))


def arrival_intro(
    nearest: NearestFlight,
    *,
    overhead: bool = False,
    page: RadarPage | None = None,
) -> tuple[DisplayItem, ...]:
    return (
        ArrivalAnimation(
            text=_matrix_text(nearest.flight.label),
            bearing_degrees=nearest.bearing_degrees,
            overhead=overhead,
            page=page,
        ),
    )


def status_pages(message: str) -> tuple[DisplayItem, ...]:
    return (DisplayPage(text=_matrix_text(message)),)


def radar_pages(
    nearest: NearestFlight,
    tracked: Sequence[NearestFlight],
    *,
    range_nautical_miles: float,
    limit: int = 0,
    stale: bool = False,
    overhead: bool = False,
    seconds: float = 0.5,
) -> tuple[RadarPage, ...]:
    flight = nearest.flight
    speed = f"{round(flight.speed_knots):d}KT" if flight.speed_knots is not None else "--KT"
    trend = trend_value(flight.vertical_rate_fpm)
    return (
        RadarPage(
            range_nautical_miles=range_nautical_miles,
            tracks=radar_tracks(tracked, nearest=nearest, limit=limit),
            label=_matrix_text(flight.label),
            detail=(
                _matrix_text(
                    " ".join(
                        part
                        for part in (flight.aircraft_type, _altitude_text(flight.altitude_feet))
                        if part
                    )
                ),
                _matrix_text(f"{speed} {_trend_text(flight.vertical_rate_fpm)}"),
            ),
            distance_text=_distance_text(nearest.distance_nautical_miles),
            compass=compass_point(nearest.bearing_degrees),
            trend=trend,
            heading_degrees=flight.heading_degrees,
            stale=stale,
            overhead=overhead,
            seconds=seconds,
        ),
    )


def radar_idle_pages(
    message: str,
    *,
    range_nautical_miles: float,
    seconds: float = 0.5,
) -> tuple[RadarPage, ...]:
    return (
        RadarPage(
            range_nautical_miles=range_nautical_miles,
            label=_matrix_text(message),
            seconds=seconds,
        ),
    )


def radar_tracks(
    tracked: Sequence[NearestFlight],
    *,
    nearest: NearestFlight | None = None,
    limit: int = 0,
) -> tuple[RadarTrack, ...]:
    """The nearest `limit` aircraft. A 64x64 dial turns to noise much beyond a handful."""
    nearest_label = nearest.flight.label if nearest is not None else None
    selected = sorted(tracked, key=lambda candidate: candidate.distance_nautical_miles)
    if limit > 0:
        selected = selected[:limit]
    return tuple(
        RadarTrack(
            label=_matrix_text(candidate.flight.label),
            distance_nautical_miles=candidate.distance_nautical_miles,
            bearing_degrees=candidate.bearing_degrees,
            trend=trend_value(candidate.flight.vertical_rate_fpm),
            nearest=candidate.flight.label == nearest_label,
        )
        for candidate in selected
    )


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
