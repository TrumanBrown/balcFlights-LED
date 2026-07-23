# balcFlights-LED

Display the nearest usable live aircraft on a four-module MAX7219 LED matrix attached to a Raspberry Pi 4.

The application consumes the public, read-only [Seattle Balc Flights API](https://seattlebalc.com/api/v1/flights), computes great-circle distance and bearing from a configured reference point, and presents compact pages instead of a long blocking marquee:

1. Bearing arrow and callsign, registration, or ICAO identifier
2. Distance in nautical miles
3. Altitude and climb/descent trend
4. Ground speed when available

Upstream failures are not presented as quiet airspace. A recent last-known aircraft is marked stale, and expired data becomes an explicit `DATA?` or `OFFLINE` state.

## Hardware Profile

Existing programs on this Pi consistently identify the display as four daisy-chained MAX7219 8x8 modules, giving a 32x8 monochrome matrix. The verified software profile is:

```toml
[matrix]
spi_port = 0
spi_device = 0
cascaded = 4
block_orientation = -90
rotate = 0
reverse_order = false
contrast = 64
```

The old programs use hardware SPI0/CE0 through `luma.led_matrix`. That implies this Pi pin mapping:

| MAX7219 module | Pi signal | BCM | Physical pin |
| --- | --- | ---: | ---: |
| `DIN` | SPI0 MOSI | GPIO10 | 19 |
| `CLK` | SPI0 SCLK | GPIO11 | 23 |
| `CS` / `LOAD` | SPI0 CE0 | GPIO8 | 24 |
| `GND` | Ground | - | 6 or another ground pin |
| `VCC` | 5V supply | - | 2 or 4 |

The signal mapping is inferred from working source and the live `/dev/spidev0.0` device, not from physically tracing wires. Confirm module labels before rewiring. Four MAX7219 boards can draw substantial current at high brightness; use a suitable regulated 5V supply with common ground rather than increasing brightness blindly.

## Setup

Python 3.11 and SPI are already available on the target Pi. Keep this project isolated from historical environments:

```bash
cd ~/projects/new/balcFlights-LED
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp balc.example.toml balc.local.toml
```

`balc.local.toml`, `.venv`, the supplied site archive, and its extracted `reference/` tree are intentionally ignored by Git.

## Configuration

The current local configuration uses the API's public default center at `47.6175, -122.305`. To use a different reference point, edit only `balc.local.toml` or set environment variables:

```text
BFL_LATITUDE
BFL_LONGITUDE
BFL_SEARCH_RADIUS_NM
BFL_API_ENDPOINT
BFL_API_TIMEOUT
BFL_REFRESH_SECONDS
BFL_MAXIMUM_SEEN_SECONDS
BFL_LAST_KNOWN_TTL_SECONDS
BFL_RENDERER
BFL_PAGE_SECONDS
BFL_SPI_PORT
BFL_SPI_DEVICE
BFL_CASCADED
BFL_BLOCK_ORIENTATION
BFL_ROTATE
BFL_REVERSE_ORDER
BFL_CONTRAST
```

The refresh interval cannot be set below 20 seconds because the public API advertises `max-age=20`. Aircraft reported on the ground or older than `maximum_seen_seconds` are excluded by default.

## Run

Validate the API and selection path without opening SPI:

```bash
.venv/bin/balc-flights-led once
```

Run the short physical orientation test:

```bash
.venv/bin/balc-flights-led matrix-test
```

Run continuously with the configured renderer:

```bash
.venv/bin/balc-flights-led run
```

Override the renderer for diagnosis:

```bash
.venv/bin/balc-flights-led run --renderer console
```

## Tests And Quality

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The test suite covers geodesic selection, nullable API fields, major-version rejection, invalid positions, cache-aware polling configuration, compact display pages, and fresh/degraded/offline/last-known state transitions.

## API Reference

The user-supplied `Seattle_Balc-main.zip` was integrity-checked and extracted to the ignored `reference/Seattle_Balc-main/` directory for local API review. This repository does not republish the friend's dashboard source. The consumer contract is documented publicly at [seattlebalc.com](https://seattlebalc.com/API.md).