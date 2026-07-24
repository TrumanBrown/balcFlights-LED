# balcFlights-LED

Display the nearest usable live aircraft on a four-module MAX7219 LED matrix attached to a Raspberry Pi 4.

The application consumes the public, read-only [Seattle Balc Flights API](https://seattlebalc.com/api/v1/flights), computes great-circle distance and bearing from a configured reference point, and presents compact pages instead of a long blocking marquee:

1. Bearing arrow and callsign, registration, or ICAO identifier
2. Distance in nautical miles
3. Altitude and climb/descent trend
4. Ground speed when available

Upstream failures are not presented as quiet airspace. A recent last-known aircraft is marked stale, and expired data becomes an explicit `DATA?` or `OFFLINE` state.

## Hardware Profile

Existing programs on this Pi consistently identify the display as four daisy-chained MAX7219 8x8 modules, giving a 32x8 monochrome matrix. The baseline software profile is:

```toml
[matrix]
spi_port = 0
spi_device = 0
spi_speed_hz = 500000
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

The signal mapping is inferred from legacy source and the live `/dev/spidev0.0` device, not from physically tracing wires. Confirm the module's input-side labels before rewiring.

Four MAX7219 boards must not be treated like a single low-current Pi accessory. Use a regulated external 5 V supply with adequate current capacity and connect its ground to Pi ground. Convert the Pi's 3.3 V DIN, CLK, and CS/LOAD signals to 5 V logic, preferably with a `74AHCT125` or equivalent 3.3 V-compatible buffer powered at 5 V. Add local 100 nF ceramic and 10 uF bulk decoupling near the matrix chain. Direct 3.3 V drive is outside the MAX7219's guaranteed input-high tolerance and is known to produce intermittent or garbled cascaded displays.

See [MAX7219 hardware troubleshooting](docs/MAX7219_TROUBLESHOOTING.md) for the evidence collected on this Pi and a pin-by-pin recovery procedure.

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
BFL_SPI_SPEED_HZ
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

First prove basic bus communication without fonts or orientation:

```bash
.venv/bin/python tools/matrix_bus_test.py
```

The expected phases are fully dark, every LED on, then fully dark. If the physical display never changes, stop adjusting `rotate` and `block_orientation`; those settings cannot affect the MAX7219 display-test or shutdown registers.

Clear and place the chain into low-power shutdown:

```bash
.venv/bin/python tools/clear_matrix.py
```

If its letters are unclear, use the focused calibration script. It uses the
`CP437_FONT` and hardware settings from the known-working legacy text programs,
shows one boxed module number at a time, then displays `1234` and scrolls
`ABCD 1234`:

```bash
# Dedicated legacy text-test orientation
.venv/bin/python tools/matrix_orientation_test.py --rotate 2

# Later DOA-program orientation
.venv/bin/python tools/matrix_orientation_test.py --rotate 0
```

Keep `block_orientation=-90` and normal module order for the first comparison.
Only test `--block-orientation 90` or `--reverse-order` if both rotations still
show internally rotated or physically reversed modules.

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