from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import BoundingBox, Coordinates, Flight, Projection

EXPECTED_API_MAJOR_VERSION = "1"
DEFAULT_ENDPOINT = "https://seattlebalc.com/api/v1/flights"
USER_AGENT = "balcFlights-LED/0.1 (+https://github.com/TrumanBrown/balcFlights-LED)"
# The feed is a small JSON document; anything larger is treated as hostile.
MAXIMUM_RESPONSE_BYTES = 4 * 1024 * 1024


class FlightApiError(RuntimeError):
    """The flight feed could not be retrieved."""


class FlightApiContractError(FlightApiError):
    """The server response did not match the supported public API contract."""


@dataclass(frozen=True, slots=True)
class FlightFeed:
    api_version: str
    status: str
    generated_at: str
    source: str
    warnings: tuple[str, ...]
    flights: tuple[Flight, ...]
    declared_count: int
    rejected_flights: int = 0

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded"


class FlightApiClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        *,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def fetch(self, bounds: BoundingBox) -> FlightFeed:
        separator = "&" if "?" in self._endpoint else "?"
        request_url = f"{self._endpoint}{separator}{urlencode(bounds.as_query_parameters())}"
        request = Request(
            request_url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            method="GET",
        )

        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAXIMUM_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise FlightApiError(f"flight API returned HTTP {error.code}") from error
        except (TimeoutError, URLError, OSError) as error:
            raise FlightApiError(f"flight API request failed: {error}") from error

        if len(body) > MAXIMUM_RESPONSE_BYTES:
            raise FlightApiContractError("flight API response exceeded the maximum accepted size")

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise FlightApiContractError("flight API returned invalid JSON") from error

        return parse_flight_feed(payload)


def parse_flight_feed(payload: object) -> FlightFeed:
    if not isinstance(payload, Mapping):
        raise FlightApiContractError("flight API response must be a JSON object")

    api_version = _required_string(payload.get("apiVersion"), "apiVersion")
    if api_version.split(".", maxsplit=1)[0] != EXPECTED_API_MAJOR_VERSION:
        raise FlightApiContractError(f"unsupported flight API version: {api_version}")

    status = _required_string(payload.get("status"), "status")
    if status not in {"ok", "degraded"}:
        raise FlightApiContractError(f"unsupported flight API status: {status}")

    raw_flights = payload.get("flights")
    if not isinstance(raw_flights, list):
        raise FlightApiContractError("flights must be a JSON array")

    flights: list[Flight] = []
    rejected_flights = 0
    for raw_flight in raw_flights:
        flight = _parse_flight(raw_flight)
        if flight is None:
            rejected_flights += 1
        else:
            flights.append(flight)

    raw_warnings = payload.get("warnings", [])
    warnings = (
        tuple(filter(None, (_optional_string(warning) for warning in raw_warnings)))
        if isinstance(raw_warnings, list)
        else ()
    )

    declared_count = _optional_int(payload.get("count"))
    return FlightFeed(
        api_version=api_version,
        status=status,
        generated_at=_optional_string(payload.get("generatedAt")) or "unknown",
        source=_optional_string(payload.get("source")) or "unknown",
        warnings=warnings,
        flights=tuple(flights),
        declared_count=declared_count if declared_count is not None else len(raw_flights),
        rejected_flights=rejected_flights,
    )


def _parse_flight(value: object) -> Flight | None:
    if not isinstance(value, Mapping):
        return None

    identifiers = _nested_mapping(value, "identifiers")
    airline = _nested_mapping(value, "airline")
    aircraft = _nested_mapping(value, "aircraft")
    position = _nested_mapping(value, "position")
    movement = _nested_mapping(value, "movement")
    signal = _nested_mapping(value, "signal")

    latitude = _optional_float(position.get("latitude"))
    longitude = _optional_float(position.get("longitude"))
    if latitude is None or longitude is None:
        return None

    try:
        coordinates = Coordinates(latitude=latitude, longitude=longitude)
    except ValueError:
        return None

    return Flight(
        position=coordinates,
        icao24=_optional_string(identifiers.get("icao24")),
        callsign=_optional_string(identifiers.get("callsign")),
        registration=_optional_string(identifiers.get("registration")),
        airline_name=_optional_string(airline.get("name")),
        aircraft_type=_optional_string(aircraft.get("typeCode")),
        altitude_feet=_optional_int(position.get("altitudeFeet")),
        on_ground=position.get("onGround") is True,
        speed_knots=_optional_float(movement.get("speedKnots")),
        heading_degrees=_optional_float(movement.get("headingDegrees")),
        vertical_rate_fpm=_optional_int(movement.get("verticalRateFeetPerMinute")),
        seen_seconds_ago=_optional_float(signal.get("seenSecondsAgo")),
        data_source=_optional_string(signal.get("dataSource")),
        projection=_parse_projection(position.get("projected")),
    )


def _parse_projection(value: object) -> Projection | None:
    if not isinstance(value, Mapping):
        return None

    latitude = _optional_float(value.get("latitude"))
    longitude = _optional_float(value.get("longitude"))
    if latitude is None or longitude is None:
        return None

    try:
        position = Coordinates(latitude=latitude, longitude=longitude)
    except ValueError:
        return None

    seconds = _optional_float(value.get("projectionSeconds"))
    return Projection(
        position=position,
        seconds=max(0.0, seconds) if seconds is not None else 0.0,
        capped=value.get("capped") is True,
        method=_optional_string(value.get("method")),
    )


def _nested_mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    nested = value.get(key)
    return nested if isinstance(nested, Mapping) else {}


def _required_string(value: object, field: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise FlightApiContractError(f"{field} must be a non-empty string")
    return result


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    # Feed strings reach the log and the terminal, so drop control characters
    # rather than letting a callsign carry an escape sequence.
    stripped = "".join(character for character in value if character.isprintable()).strip()
    return stripped or None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    return round(number) if number is not None else None
