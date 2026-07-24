from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import DEFAULT_ENDPOINT
from .models import Coordinates

SUPPORTED_SPI_SPEEDS_HZ = (500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    endpoint: str = DEFAULT_ENDPOINT
    timeout_seconds: float = 10.0
    refresh_seconds: float = 30.0
    maximum_seen_seconds: float = 60.0
    last_known_ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise ValueError("api.endpoint must use HTTPS")
        if self.timeout_seconds <= 0:
            raise ValueError("api.timeout_seconds must be greater than 0")
        if self.refresh_seconds < 20:
            raise ValueError("api.refresh_seconds must respect the API's 20-second cache")
        if self.maximum_seen_seconds < 0:
            raise ValueError("api.maximum_seen_seconds cannot be negative")
        if self.last_known_ttl_seconds < self.refresh_seconds:
            raise ValueError("api.last_known_ttl_seconds must be at least one refresh interval")


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    renderer: str = "console"
    page_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.renderer not in {"console", "matrix"}:
            raise ValueError("display.renderer must be 'console' or 'matrix'")
        if self.page_seconds <= 0:
            raise ValueError("display.page_seconds must be greater than 0")


@dataclass(frozen=True, slots=True)
class MatrixSettings:
    spi_port: int = 0
    spi_device: int = 0
    spi_speed_hz: int = 500_000
    cascaded: int = 4
    block_orientation: int = -90
    rotate: int = 0
    reverse_order: bool = False
    contrast: int = 64

    def __post_init__(self) -> None:
        if self.spi_port < 0 or self.spi_device < 0:
            raise ValueError("matrix SPI port and device cannot be negative")
        if self.spi_speed_hz not in SUPPORTED_SPI_SPEEDS_HZ:
            supported = ", ".join(str(speed) for speed in SUPPORTED_SPI_SPEEDS_HZ)
            raise ValueError(f"matrix.spi_speed_hz must be one of: {supported}")
        if self.cascaded <= 0:
            raise ValueError("matrix.cascaded must be greater than 0")
        if self.block_orientation not in {-90, 0, 90, 180}:
            raise ValueError("matrix.block_orientation must be -90, 0, 90, or 180")
        if self.rotate not in {0, 1, 2, 3}:
            raise ValueError("matrix.rotate must be 0, 1, 2, or 3")
        if not 0 <= self.contrast <= 255:
            raise ValueError("matrix.contrast must be between 0 and 255")


@dataclass(frozen=True, slots=True)
class Settings:
    location: Coordinates
    search_radius_nautical_miles: float
    api: ApiSettings
    display: DisplaySettings
    matrix: MatrixSettings

    def __post_init__(self) -> None:
        if not 0 < self.search_radius_nautical_miles <= 250:
            raise ValueError("location.search_radius_nautical_miles must be between 0 and 250")


def load_settings(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    config_path = path or Path("balc.local.toml")
    document: Mapping[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as config_file:
            loaded = tomllib.load(config_file)
        if not isinstance(loaded, Mapping):
            raise ValueError("configuration root must be a TOML table")
        document = loaded

    environment = os.environ if environ is None else environ
    location = _table(document, "location")
    api = _table(document, "api")
    display = _table(document, "display")
    matrix = _table(document, "matrix")

    return Settings(
        location=Coordinates(
            latitude=_float_value(environment, "BFL_LATITUDE", location, "latitude", 47.6175),
            longitude=_float_value(
                environment,
                "BFL_LONGITUDE",
                location,
                "longitude",
                -122.305,
            ),
        ),
        search_radius_nautical_miles=_float_value(
            environment,
            "BFL_SEARCH_RADIUS_NM",
            location,
            "search_radius_nautical_miles",
            20.0,
        ),
        api=ApiSettings(
            endpoint=_string_value(
                environment, "BFL_API_ENDPOINT", api, "endpoint", DEFAULT_ENDPOINT
            ),
            timeout_seconds=_float_value(
                environment, "BFL_API_TIMEOUT", api, "timeout_seconds", 10.0
            ),
            refresh_seconds=_float_value(
                environment, "BFL_REFRESH_SECONDS", api, "refresh_seconds", 30.0
            ),
            maximum_seen_seconds=_float_value(
                environment,
                "BFL_MAXIMUM_SEEN_SECONDS",
                api,
                "maximum_seen_seconds",
                60.0,
            ),
            last_known_ttl_seconds=_float_value(
                environment,
                "BFL_LAST_KNOWN_TTL_SECONDS",
                api,
                "last_known_ttl_seconds",
                300.0,
            ),
        ),
        display=DisplaySettings(
            renderer=_string_value(environment, "BFL_RENDERER", display, "renderer", "console"),
            page_seconds=_float_value(
                environment, "BFL_PAGE_SECONDS", display, "page_seconds", 2.0
            ),
        ),
        matrix=MatrixSettings(
            spi_port=_int_value(environment, "BFL_SPI_PORT", matrix, "spi_port", 0),
            spi_device=_int_value(environment, "BFL_SPI_DEVICE", matrix, "spi_device", 0),
            spi_speed_hz=_int_value(
                environment,
                "BFL_SPI_SPEED_HZ",
                matrix,
                "spi_speed_hz",
                500_000,
            ),
            cascaded=_int_value(environment, "BFL_CASCADED", matrix, "cascaded", 4),
            block_orientation=_int_value(
                environment,
                "BFL_BLOCK_ORIENTATION",
                matrix,
                "block_orientation",
                -90,
            ),
            rotate=_int_value(environment, "BFL_ROTATE", matrix, "rotate", 0),
            reverse_order=_bool_value(
                environment,
                "BFL_REVERSE_ORDER",
                matrix,
                "reverse_order",
                False,
            ),
            contrast=_int_value(environment, "BFL_CONTRAST", matrix, "contrast", 64),
        ),
    )


def _table(document: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a TOML table")
    return value


def _raw_value(
    environment: Mapping[str, str],
    environment_name: str,
    table: Mapping[str, Any],
    key: str,
    default: Any,
) -> Any:
    return environment.get(environment_name, table.get(key, default))


def _string_value(
    environment: Mapping[str, str],
    environment_name: str,
    table: Mapping[str, Any],
    key: str,
    default: str,
) -> str:
    value = _raw_value(environment, environment_name, table, key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _float_value(
    environment: Mapping[str, str],
    environment_name: str,
    table: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    value = _raw_value(environment, environment_name, table, key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be numeric") from error


def _int_value(
    environment: Mapping[str, str],
    environment_name: str,
    table: Mapping[str, Any],
    key: str,
    default: int,
) -> int:
    value = _raw_value(environment, environment_name, table, key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer") from error


def _bool_value(
    environment: Mapping[str, str],
    environment_name: str,
    table: Mapping[str, Any],
    key: str,
    default: bool,
) -> bool:
    value = _raw_value(environment, environment_name, table, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "1", "yes", "on"}:
        return True
    if isinstance(value, str) and value.lower() in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean")
