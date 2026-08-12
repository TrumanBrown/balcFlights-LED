from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api import DEFAULT_ENDPOINT
from .models import Coordinates

SUPPORTED_SPI_SPEEDS_HZ = (500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000)
RENDERER_CHOICES = ("console", "matrix", "both")
# Which physical display 'matrix' means: the cascaded MAX7219 chain, or a HUB75
# RGB panel driven by the rpi-rgb-led-matrix bindings.
PANEL_CHOICES = ("max7219", "hub75")
# Only 'atari' and 'tiny' are narrow enough to fit a callsign across 32 columns.
FONT_CHOICES = ("atari", "tiny", "lcd", "cp437", "sinclair")
HARDWARE_MAPPING_CHOICES = (
    "regular",
    "regular-pi1",
    "adafruit-hat",
    "adafruit-hat-pwm",
    "compute-module",
    "classic",
    "classic-pi1",
)
# Chipsets needing a bespoke init sequence; the empty string is a plain HUB75 panel.
PANEL_TYPE_CHOICES = ("", "FM6126A", "FM6127")


@dataclass(frozen=True, slots=True)
class ApiSettings:
    endpoint: str = DEFAULT_ENDPOINT
    timeout_seconds: float = 10.0
    refresh_seconds: float = 20.0
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
    panel: str = "max7219"
    font: str = "atari"
    page_seconds: float = 2.0
    scroll_delay: float = 0.04
    frame_seconds: float = 0.03
    animations: bool = True
    # Only a HUB75 panel has the pixels for the radar; the MAX7219 chain ignores it.
    radar: bool = True
    # How much sky the dial covers. 0 follows the search radius, which on a 64x64
    # panel squeezes 20 NM into 20 pixels and reads as noise.
    radar_range_nautical_miles: float = 10.0
    # Contacts plotted, nearest first. 0 plots every one of them.
    radar_contacts: int = 6

    def __post_init__(self) -> None:
        if self.renderer not in RENDERER_CHOICES:
            supported = ", ".join(repr(name) for name in RENDERER_CHOICES)
            raise ValueError(f"display.renderer must be one of: {supported}")
        if self.panel not in PANEL_CHOICES:
            supported = ", ".join(repr(name) for name in PANEL_CHOICES)
            raise ValueError(f"display.panel must be one of: {supported}")
        if self.font not in FONT_CHOICES:
            supported = ", ".join(repr(name) for name in FONT_CHOICES)
            raise ValueError(f"display.font must be one of: {supported}")
        if self.page_seconds <= 0:
            raise ValueError("display.page_seconds must be greater than 0")
        if self.scroll_delay < 0:
            raise ValueError("display.scroll_delay cannot be negative")
        if self.frame_seconds <= 0:
            raise ValueError("display.frame_seconds must be greater than 0")
        if self.radar_range_nautical_miles < 0:
            raise ValueError("display.radar_range_nautical_miles cannot be negative")
        if self.radar_contacts < 0:
            raise ValueError("display.radar_contacts cannot be negative")


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
class Hub75Settings:
    """Options passed straight through to rpi-rgb-led-matrix's RGBMatrixOptions."""

    rows: int = 64
    columns: int = 64
    chain_length: int = 1
    parallel: int = 1
    hardware_mapping: str = "regular"
    gpio_slowdown: int = 4
    pwm_bits: int = 11
    pwm_lsb_nanoseconds: int = 130
    brightness: int = 50
    limit_refresh_rate_hz: int = 0
    led_rgb_sequence: str = "RGB"
    panel_type: str = ""
    pixel_mapper_config: str = ""
    disable_hardware_pulsing: bool = False
    drop_privileges: bool = True

    def __post_init__(self) -> None:
        for name, value in (("rows", self.rows), ("columns", self.columns)):
            if value <= 0 or value % 8:
                raise ValueError(f"hub75.{name} must be a positive multiple of 8")
        if self.chain_length <= 0:
            raise ValueError("hub75.chain_length must be greater than 0")
        if not 1 <= self.parallel <= 3:
            raise ValueError("hub75.parallel must be 1, 2, or 3")
        if self.hardware_mapping not in HARDWARE_MAPPING_CHOICES:
            supported = ", ".join(repr(name) for name in HARDWARE_MAPPING_CHOICES)
            raise ValueError(f"hub75.hardware_mapping must be one of: {supported}")
        if not 0 <= self.gpio_slowdown <= 10:
            raise ValueError("hub75.gpio_slowdown must be between 0 and 10")
        if not 1 <= self.pwm_bits <= 11:
            raise ValueError("hub75.pwm_bits must be between 1 and 11")
        if self.pwm_lsb_nanoseconds <= 0:
            raise ValueError("hub75.pwm_lsb_nanoseconds must be greater than 0")
        if not 1 <= self.brightness <= 100:
            raise ValueError("hub75.brightness must be between 1 and 100")
        if self.limit_refresh_rate_hz < 0:
            raise ValueError("hub75.limit_refresh_rate_hz cannot be negative")
        if sorted(self.led_rgb_sequence.upper()) != ["B", "G", "R"]:
            raise ValueError("hub75.led_rgb_sequence must be a permutation of 'RGB'")
        if self.panel_type not in PANEL_TYPE_CHOICES:
            supported = ", ".join(repr(name) for name in PANEL_TYPE_CHOICES)
            raise ValueError(f"hub75.panel_type must be one of: {supported}")

    @property
    def width(self) -> int:
        return self.columns * self.chain_length

    @property
    def height(self) -> int:
        return self.rows * self.parallel


@dataclass(frozen=True, slots=True)
class Settings:
    location: Coordinates
    search_radius_nautical_miles: float
    overhead_radius_nautical_miles: float
    api: ApiSettings
    display: DisplaySettings
    matrix: MatrixSettings
    hub75: Hub75Settings = field(default_factory=Hub75Settings)

    def __post_init__(self) -> None:
        if not 0 < self.search_radius_nautical_miles <= 250:
            raise ValueError("location.search_radius_nautical_miles must be between 0 and 250")
        if not 0 < self.overhead_radius_nautical_miles <= self.search_radius_nautical_miles:
            raise ValueError(
                "location.overhead_radius_nautical_miles must be between 0 and the search radius"
            )


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
    hub75 = _table(document, "hub75")

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
        overhead_radius_nautical_miles=_float_value(
            environment,
            "BFL_OVERHEAD_RADIUS_NM",
            location,
            "overhead_radius_nautical_miles",
            1.5,
        ),
        api=ApiSettings(
            endpoint=_string_value(
                environment, "BFL_API_ENDPOINT", api, "endpoint", DEFAULT_ENDPOINT
            ),
            timeout_seconds=_float_value(
                environment, "BFL_API_TIMEOUT", api, "timeout_seconds", 10.0
            ),
            refresh_seconds=_float_value(
                environment, "BFL_REFRESH_SECONDS", api, "refresh_seconds", 20.0
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
            panel=_string_value(environment, "BFL_PANEL", display, "panel", "max7219"),
            font=_string_value(environment, "BFL_FONT", display, "font", "atari"),
            page_seconds=_float_value(
                environment, "BFL_PAGE_SECONDS", display, "page_seconds", 2.0
            ),
            scroll_delay=_float_value(
                environment, "BFL_SCROLL_DELAY", display, "scroll_delay", 0.04
            ),
            frame_seconds=_float_value(
                environment, "BFL_FRAME_SECONDS", display, "frame_seconds", 0.03
            ),
            animations=_bool_value(environment, "BFL_ANIMATIONS", display, "animations", True),
            radar=_bool_value(environment, "BFL_RADAR", display, "radar", True),
            radar_range_nautical_miles=_float_value(
                environment,
                "BFL_RADAR_RANGE_NM",
                display,
                "radar_range_nautical_miles",
                10.0,
            ),
            radar_contacts=_int_value(
                environment,
                "BFL_RADAR_CONTACTS",
                display,
                "radar_contacts",
                6,
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
        hub75=Hub75Settings(
            rows=_int_value(environment, "BFL_HUB75_ROWS", hub75, "rows", 64),
            columns=_int_value(environment, "BFL_HUB75_COLUMNS", hub75, "columns", 64),
            chain_length=_int_value(environment, "BFL_HUB75_CHAIN", hub75, "chain_length", 1),
            parallel=_int_value(environment, "BFL_HUB75_PARALLEL", hub75, "parallel", 1),
            hardware_mapping=_string_value(
                environment,
                "BFL_HUB75_MAPPING",
                hub75,
                "hardware_mapping",
                "regular",
            ),
            gpio_slowdown=_int_value(
                environment,
                "BFL_HUB75_GPIO_SLOWDOWN",
                hub75,
                "gpio_slowdown",
                4,
            ),
            pwm_bits=_int_value(environment, "BFL_HUB75_PWM_BITS", hub75, "pwm_bits", 11),
            pwm_lsb_nanoseconds=_int_value(
                environment,
                "BFL_HUB75_PWM_LSB_NS",
                hub75,
                "pwm_lsb_nanoseconds",
                130,
            ),
            brightness=_int_value(environment, "BFL_HUB75_BRIGHTNESS", hub75, "brightness", 50),
            limit_refresh_rate_hz=_int_value(
                environment,
                "BFL_HUB75_LIMIT_REFRESH_HZ",
                hub75,
                "limit_refresh_rate_hz",
                0,
            ),
            led_rgb_sequence=_string_value(
                environment,
                "BFL_HUB75_RGB_SEQUENCE",
                hub75,
                "led_rgb_sequence",
                "RGB",
            ),
            panel_type=_optional_string_value(
                environment,
                "BFL_HUB75_PANEL_TYPE",
                hub75,
                "panel_type",
            ),
            pixel_mapper_config=_optional_string_value(
                environment,
                "BFL_HUB75_PIXEL_MAPPER",
                hub75,
                "pixel_mapper_config",
            ),
            disable_hardware_pulsing=_bool_value(
                environment,
                "BFL_HUB75_NO_HARDWARE_PULSE",
                hub75,
                "disable_hardware_pulsing",
                False,
            ),
            drop_privileges=_bool_value(
                environment,
                "BFL_HUB75_DROP_PRIVILEGES",
                hub75,
                "drop_privileges",
                True,
            ),
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


def _optional_string_value(
    environment: Mapping[str, str],
    environment_name: str,
    table: Mapping[str, Any],
    key: str,
) -> str:
    value = _raw_value(environment, environment_name, table, key, "")
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
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
