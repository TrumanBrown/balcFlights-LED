from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be a finite value between -90 and 90")
        if not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be a finite value between -180 and 180")


@dataclass(frozen=True, slots=True)
class Flight:
    position: Coordinates
    icao24: str | None = None
    callsign: str | None = None
    registration: str | None = None
    airline_name: str | None = None
    aircraft_type: str | None = None
    altitude_feet: int | None = None
    on_ground: bool = False
    speed_knots: float | None = None
    heading_degrees: float | None = None
    vertical_rate_fpm: int | None = None
    seen_seconds_ago: float | None = None
    data_source: str | None = None

    @property
    def label(self) -> str:
        for value in (self.callsign, self.registration, self.icao24):
            if value and value.strip():
                return value.strip().upper()
        return "UNKNOWN"


@dataclass(frozen=True, slots=True)
class NearestFlight:
    flight: Flight
    distance_nautical_miles: float
    bearing_degrees: float


@dataclass(frozen=True, slots=True)
class BoundingBox:
    minimum_latitude: float
    minimum_longitude: float
    maximum_latitude: float
    maximum_longitude: float

    def as_query_parameters(self) -> dict[str, float]:
        return {
            "lamin": round(self.minimum_latitude, 6),
            "lomin": round(self.minimum_longitude, 6),
            "lamax": round(self.maximum_latitude, 6),
            "lomax": round(self.maximum_longitude, 6),
        }
