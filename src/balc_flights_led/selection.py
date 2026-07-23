from __future__ import annotations

import math
from collections.abc import Iterable

from .models import BoundingBox, Coordinates, Flight, NearestFlight

EARTH_RADIUS_NAUTICAL_MILES = 3440.065
NAUTICAL_MILES_PER_LATITUDE_DEGREE = 60.0405


def distance_nautical_miles(origin: Coordinates, destination: Coordinates) -> float:
    latitude_1 = math.radians(origin.latitude)
    latitude_2 = math.radians(destination.latitude)
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = math.radians(destination.longitude - origin.longitude)

    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(longitude_delta / 2) ** 2
    )
    central_angle = 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
    return EARTH_RADIUS_NAUTICAL_MILES * central_angle


def initial_bearing_degrees(origin: Coordinates, destination: Coordinates) -> float:
    latitude_1 = math.radians(origin.latitude)
    latitude_2 = math.radians(destination.latitude)
    longitude_delta = math.radians(destination.longitude - origin.longitude)

    east_component = math.sin(longitude_delta) * math.cos(latitude_2)
    north_component = math.cos(latitude_1) * math.sin(latitude_2) - math.sin(latitude_1) * math.cos(
        latitude_2
    ) * math.cos(longitude_delta)
    return (math.degrees(math.atan2(east_component, north_component)) + 360) % 360


def bounds_around(origin: Coordinates, radius_nautical_miles: float) -> BoundingBox:
    if not math.isfinite(radius_nautical_miles) or not 0 < radius_nautical_miles <= 250:
        raise ValueError("radius_nautical_miles must be greater than 0 and at most 250")

    latitude_delta = radius_nautical_miles / NAUTICAL_MILES_PER_LATITUDE_DEGREE
    longitude_scale = math.cos(math.radians(origin.latitude))
    if abs(longitude_scale) < 1e-9:
        longitude_delta = 180.0
    else:
        longitude_delta = min(180.0, latitude_delta / abs(longitude_scale))

    return BoundingBox(
        minimum_latitude=max(-90.0, origin.latitude - latitude_delta),
        minimum_longitude=max(-180.0, origin.longitude - longitude_delta),
        maximum_latitude=min(90.0, origin.latitude + latitude_delta),
        maximum_longitude=min(180.0, origin.longitude + longitude_delta),
    )


def nearest_flight(
    flights: Iterable[Flight],
    origin: Coordinates,
    *,
    include_on_ground: bool = False,
    maximum_seen_seconds: float = 60.0,
) -> NearestFlight | None:
    candidates: list[NearestFlight] = []

    for flight in flights:
        if flight.on_ground and not include_on_ground:
            continue
        if flight.seen_seconds_ago is not None and flight.seen_seconds_ago > maximum_seen_seconds:
            continue

        candidates.append(
            NearestFlight(
                flight=flight,
                distance_nautical_miles=distance_nautical_miles(origin, flight.position),
                bearing_degrees=initial_bearing_degrees(origin, flight.position),
            )
        )

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda candidate: (
            candidate.distance_nautical_miles,
            candidate.flight.seen_seconds_ago
            if candidate.flight.seen_seconds_ago is not None
            else math.inf,
            candidate.flight.label,
        ),
    )
