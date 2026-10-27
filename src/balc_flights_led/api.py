from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .models import BoundingBox, Coordinates, Flight, Projection

EXPECTED_API_MAJOR_VERSION = "1"
DEFAULT_ENDPOINT = "https://seattlebalc.com/api/v1/flights"
USER_AGENT = "balcFlights-LED/0.1 (+https://github.com/TrumanBrown/balcFlights-LED)"
# The feed is a small JSON document; anything larger is treated as hostile.
MAXIMUM_RESPONSE_BYTES = 4 * 1024 * 1024
# Identifiers are drawn on the panel and fitted a character at a time, so a
# multi-megabyte callsign would stall the renderer. Real ones are under 10.
MAXIMUM_IDENTIFIER_LENGTH = 16
MAXIMUM_TEXT_LENGTH = 200
MAXIMUM_WARNINGS = 10
# Values outside these ranges are treated as missing rather than trusted, so a
# hostile feed cannot push the dead reckoning into overflow.
SPEED_KNOTS_RANGE = (0.0, 2000.0)
ALTITUDE_FEET_RANGE = (-2000.0, 100_000.0)
HEADING_DEGREES_RANGE = (0.0, 360.0)
VERTICAL_RATE_FPM_RANGE = (-30_000.0, 30_000.0)


class FlightApiError(RuntimeError):
    """The flight feed could not be retrieved."""


class FlightApiContractError(FlightApiError):
    """The server response did not match the supported public API contract."""


class _HttpsOnlyRedirects(HTTPRedirectHandler):
    """Follow redirects only while they stay on HTTPS."""

    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        if urlsplit(newurl).scheme != "https":
            raise FlightApiError("flight API redirected away from HTTPS; refusing to follow")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_HTTPS_OPENER = build_opener(_HttpsOnlyRedirects)


def https_open(request: Request, *, timeout: float) -> Any:
    return _HTTPS_OPENER.open(request, timeout=timeout)


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
        opener: Callable[..., Any] = https_open,
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
                final_url = getattr(response, "geturl", lambda: request_url)()
                if urlsplit(final_url).scheme != "https":
                    raise FlightApiError("flight API response did not arrive over HTTPS")
                body = response.read(MAXIMUM_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise FlightApiError(f"flight API returned HTTP {error.code}") from error
        except (TimeoutError, URLError, OSError) as error:
            raise FlightApiError(f"flight API request failed: {error}") from error
        except HTTPException as error:
            # The message can carry raw bytes from the server, so only the type is reported.
            raise FlightApiError(f"flight API request failed: {type(error).__name__}") from error

        if len(body) > MAXIMUM_RESPONSE_BYTES:
            raise FlightApiContractError("flight API response exceeded the maximum accepted size")

        try:
            payload = json.loads(body)
        except (ValueError, RecursionError) as error:
            # ValueError covers malformed JSON, bad UTF-8, and integers too long to convert.
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
    warnings: tuple[str, ...] = ()
    if isinstance(raw_warnings, list):
        cleaned = (_optional_string(warning) for warning in raw_warnings)
        warnings = tuple(warning for warning in cleaned if warning)[:MAXIMUM_WARNINGS]

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
        icao24=_identifier(identifiers.get("icao24")),
        callsign=_identifier(identifiers.get("callsign")),
        registration=_identifier(identifiers.get("registration")),
        airline_name=_optional_string(airline.get("name")),
        aircraft_type=_identifier(aircraft.get("typeCode")),
        altitude_feet=_bounded_int(position.get("altitudeFeet"), ALTITUDE_FEET_RANGE),
        on_ground=position.get("onGround") is True,
        speed_knots=_bounded_float(movement.get("speedKnots"), SPEED_KNOTS_RANGE),
        heading_degrees=_bounded_float(movement.get("headingDegrees"), HEADING_DEGREES_RANGE),
        vertical_rate_fpm=_bounded_int(
            movement.get("verticalRateFeetPerMinute"), VERTICAL_RATE_FPM_RANGE
        ),
        seen_seconds_ago=_non_negative(_optional_float(signal.get("seenSecondsAgo"))),
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


def _optional_string(value: object, maximum_length: int = MAXIMUM_TEXT_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    # Feed strings reach the log and the terminal, so drop control characters
    # rather than letting a callsign carry an escape sequence.
    stripped = "".join(character for character in value if character.isprintable()).strip()
    return stripped[:maximum_length].strip() or None


def _identifier(value: object) -> str | None:
    return _optional_string(value, MAXIMUM_IDENTIFIER_LENGTH)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    return round(number) if number is not None else None


def _bounded_float(value: object, limits: tuple[float, float]) -> float | None:
    number = _optional_float(value)
    if number is None or not limits[0] <= number <= limits[1]:
        return None
    return number


def _bounded_int(value: object, limits: tuple[float, float]) -> int | None:
    number = _bounded_float(value, limits)
    return round(number) if number is not None else None


def _non_negative(value: float | None) -> float | None:
    return max(0.0, value) if value is not None else None
