from __future__ import annotations

import math
from collections.abc import Iterable

from .models import BoundingBox, Coordinates, Flight, NearestFlight

EARTH_RADIUS_NAUTICAL_MILES = 3440.065
NAUTICAL_MILES_PER_LATITUDE_DEGREE = 60.0405
# The API caps its own projection at 45s. Local extrapolation honours the same
# ceiling so the display never invents a position the upstream would refuse to.
MAXIMUM_PROJECTION_SECONDS = 45.0


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


def advance_position(
    origin: Coordinates,
    bearing_degrees: float,
    distance_nautical_miles: float,
) -> Coordinates:
    """Great-circle destination reached by travelling a bearing for a distance."""
    if distance_nautical_miles <= 0:
        return origin

    angular_distance = distance_nautical_miles / EARTH_RADIUS_NAUTICAL_MILES
    bearing = math.radians(bearing_degrees)
    latitude_1 = math.radians(origin.latitude)
    longitude_1 = math.radians(origin.longitude)

    sine_latitude_2 = math.sin(latitude_1) * math.cos(angular_distance) + math.cos(
        latitude_1
    ) * math.sin(angular_distance) * math.cos(bearing)
    latitude_2 = math.asin(min(1.0, max(-1.0, sine_latitude_2)))

    east_component = math.sin(bearing) * math.sin(angular_distance) * math.cos(latitude_1)
    north_component = math.cos(angular_distance) - math.sin(latitude_1) * math.sin(latitude_2)
    longitude_2 = longitude_1 + math.atan2(east_component, north_component)

    return Coordinates(
        latitude=math.degrees(latitude_2),
        longitude=(math.degrees(longitude_2) + 540) % 360 - 180,
    )


def estimated_position(flight: Flight, elapsed_seconds: float = 0.0) -> Coordinates:
    """Where the aircraft is now, preferring the API's projection over the raw fix."""
    if flight.projection is not None:
        base = flight.projection.position
        already_projected = flight.projection.seconds
    else:
        base = flight.position
        already_projected = flight.seen_seconds_ago or 0.0

    if flight.on_ground or flight.speed_knots is None or flight.heading_degrees is None:
        return base

    budget = MAXIMUM_PROJECTION_SECONDS - already_projected
    advance_seconds = min(max(0.0, elapsed_seconds), max(0.0, budget))
    if advance_seconds <= 0:
        return base

    return advance_position(
        base,
        flight.heading_degrees,
        flight.speed_knots * advance_seconds / 3600.0,
    )


def nearest_flight(
    flights: Iterable[Flight],
    origin: Coordinates,
    *,
    include_on_ground: bool = False,
    maximum_seen_seconds: float = 60.0,
    elapsed_seconds: float = 0.0,
) -> NearestFlight | None:
    candidates: list[NearestFlight] = []

    for flight in flights:
        if flight.on_ground and not include_on_ground:
            continue
        if (
            flight.seen_seconds_ago is not None
            and flight.seen_seconds_ago + elapsed_seconds > maximum_seen_seconds
        ):
            continue

        position = estimated_position(flight, elapsed_seconds)
        candidates.append(
            NearestFlight(
                flight=flight,
                distance_nautical_miles=distance_nautical_miles(origin, position),
                bearing_degrees=initial_bearing_degrees(origin, position),
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
