# balcFlights-LED

Display the aircraft currently overhead on a four-module MAX7219 LED matrix attached to a Raspberry Pi 4.

The application consumes the public, read-only [Seattle Balc Flights API](https://seattlebalc.com/api/v1/flights), computes great-circle distance and bearing from a configured reference point, and drives a 32x8 monochrome matrix.

## What The Matrix Shows

The callsign of the nearest aircraft is on screen at all times. Everything else uses the space the callsign leaves over.

```text
Q X E 2 3 7 2 |^|     callsign (rows 0-5) + indicator cell (right)
###########...        proximity bar (row 7)
```

| Element | Where | Behaviour |
| --- | --- | --- |
| Callsign | Rows 0-5, left | Always visible. Registration or ICAO identifier when there is no callsign. |
| Proximity bar | Row 7, full width | Longer means closer. Full width is directly overhead, empty is the edge of the search radius. |
| Indicator cell | Rows 0-5, right of the callsign | Alternates each `display.page_seconds` between the bearing arrow and the climb/level/descent chevrons. |
| Overhead marker | Indicator cell | The cell inverts to a dark glyph on a lit block while inside `location.overhead_radius_nautical_miles`. |
| Stale marker | Top-right pixel | Lit when the data is last-known rather than live. |
| Detail scroll | Full width | Once per cycle: `ASA123 B739 2.4NM SE 5500FT CLB 266KT`. |
| Arrival animation | Full width | When the nearest aircraft *changes*, a plane sprite flies past, then the new callsign is revealed column by column. |
| Idle | Full width | Drifting dots alternating with `NO FLT` when no aircraft qualifies. |

Bearing arrows have a shaft; climb and descent chevrons deliberately do not, so an aircraft to the north never looks like one that is climbing.

A six-character callsign such as `ASA123` is 24 px, leaving 8 columns for the indicator. A seven-character callsign such as `QXE2372` is 28 px, leaving 4 — enough for a narrower version of the same glyphs. Only a callsign that fills all 32 columns suppresses the indicator entirely.

Upstream failures are not presented as quiet airspace. A recent last-known aircraft is marked stale, and expired data becomes an explicit `DATA?` or `OFFLINE` state.

Set `display.animations = false` to suppress the arrival sprite and show content changes immediately.

### Fonts

`display.font` selects the callsign font. The layout adapts automatically: the renderer measures which rows the font inks, lifts the glyphs to the top, and puts the proximity bar in the rows left over.

| Font | `ASA123` | `QXE2372` | Rows inked | Leaves a bar row |
| --- | ---: | ---: | ---: | --- |
| `atari` (default) | 24 px | 28 px | 6 | yes |
| `tiny` | 24 px | 28 px | 5 | yes |
| `lcd` | 34 px | 42 px | 8 | no |
| `cp437` | 42 px | 51 px | 8 | no |
| `sinclair` | 41 px | 49 px | 8 | no |

`atari` and `tiny` are the same width, but `atari` uses six rows rather than five, so it is markedly easier to read. The wider fonts will truncate callsigns and leave no room for the bar. The detail scroll always uses `cp437`, because a marquee has unlimited width.

## Hardware Profile

The display is four daisy-chained MAX7219 8x8 modules, giving a 32x8 monochrome matrix on hardware SPI0/CE0. This profile is **verified working on this Pi**:

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

[tools/no-ai-matrix-test.py](tools/no-ai-matrix-test.py) is the hand-verified baseline that established this configuration. It uses luma's default bus speed and contrast rather than the values above; both work. Any driver change must still pass that script.

Pin mapping for SPI0/CE0:

| MAX7219 module | Pi signal | BCM | Physical pin |
| --- | --- | ---: | ---: |
| `DIN` | SPI0 MOSI | GPIO10 | 19 |
| `CLK` | SPI0 SCLK | GPIO11 | 23 |
| `CS` / `LOAD` | SPI0 CE0 | GPIO8 | 24 |
| `GND` | Ground | - | 6 or another ground pin |
| `VCC` | 5V supply | - | 2 or 4 |

Four MAX7219 boards must not be treated like a single low-current Pi accessory. Use a regulated external 5 V supply with adequate current capacity and connect its ground to Pi ground. The Pi's 3.3 V DIN, CLK, and CS/LOAD outputs are below the MAX7219's guaranteed input-high threshold; a `74AHCT125` or equivalent 5 V-powered buffer removes that margin problem. Add local 100 nF ceramic and 10 uF bulk decoupling near the matrix chain. The conservative 500 kHz clock is retained for the same reason.

See [MAX7219 hardware troubleshooting](docs/MAX7219_TROUBLESHOOTING.md) for the diagnostic history and a pin-by-pin recovery procedure.

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
BFL_OVERHEAD_RADIUS_NM
BFL_API_ENDPOINT
BFL_API_TIMEOUT
BFL_REFRESH_SECONDS
BFL_MAXIMUM_SEEN_SECONDS
BFL_LAST_KNOWN_TTL_SECONDS
BFL_RENDERER
BFL_FONT
BFL_PAGE_SECONDS
BFL_SCROLL_DELAY
BFL_FRAME_SECONDS
BFL_ANIMATIONS
BFL_SPI_PORT
BFL_SPI_DEVICE
BFL_SPI_SPEED_HZ
BFL_CASCADED
BFL_BLOCK_ORIENTATION
BFL_ROTATE
BFL_REVERSE_ORDER
BFL_CONTRAST
```

The refresh interval cannot be set below 20 seconds because the public API advertises `max-age=20`. Aircraft reported on the ground or older than `maximum_seen_seconds` are excluded by default. `overhead_radius_nautical_miles` must be greater than zero and no larger than the search radius.

`scroll_delay` controls the detail marquee, `frame_seconds` controls the arrival and idle animations. Both trade smoothness against SPI bandwidth at 500 kHz.

## Run

One file starts the live display:

```bash
cd ~/projects/new/balcFlights-LED
.venv/bin/python run.py
```

That polls the API every 30 seconds and drives the matrix until you press Ctrl+C, which blanks it. Nothing else needs to be running.

`display.renderer` accepts three values, and `--renderer` overrides it:

| Value | Effect |
| --- | --- |
| `matrix` | LED matrix only |
| `console` | Terminal only; never opens SPI |
| `both` | Matrix *and* a printed line per frame, so you can see what the matrix is doing |

```bash
.venv/bin/python run.py --renderer both
.venv/bin/python run.py --renderer console
```

Console output looks like this, one line per frame:

```text
1.5NM | bearing=163 | OVERHEAD
SKW4043 | OVERHEAD
[scroll] SKW4043 E75L 1.5NM S 5750FT CLB 265KT
[arrival] SKW4043
```

To see every visual immediately instead of waiting for real traffic:

```bash
.venv/bin/python tests/run_tests.py --matrix-only --phase visuals
```

The installed console script is equivalent to `run.py` and takes the same options:

```bash
.venv/bin/balc-flights-led run                  # same as run.py
.venv/bin/balc-flights-led once                 # one API fetch, printed, no SPI
.venv/bin/balc-flights-led once --renderer matrix
```

`once` is the quickest way to confirm the API and your coordinates are right before involving hardware.

## Hardware Checks

`tests/run_tests.py` is the single entry point for every check. By default it runs the unit tests only and never opens SPI:

```bash
.venv/bin/python tests/run_tests.py
```

Add `--matrix` to also drive the physical chain, or `--matrix-only` to skip the software tests:

```bash
.venv/bin/python tests/run_tests.py --matrix
```

That runs four phases in order and always blanks the chain on exit:

| Phase | What it proves |
| --- | --- |
| `wiring` | Raw display-test register toggle: dark, every LED on, dark. Proves VCC/GND/DIN/CLK/CS. |
| `blocks` | Lights each 8x8 block in turn. Proves `matrix.cascaded`. |
| `visuals` | Every frame the application can draw, including the arrival animation and idle drift. |
| `off` | Clears every row and enters shutdown. |

Isolate one phase when narrowing something down, or blank a stuck display:

```bash
.venv/bin/python tests/run_tests.py --matrix-only --phase wiring
.venv/bin/python tests/run_tests.py --matrix-only --phase off
```

If the `wiring` phase never changes the display, stop adjusting `rotate` and
`block_orientation`; those settings cannot affect the MAX7219 display-test or
shutdown registers, so the fault is power or signal wiring.

The off sequence intentionally repeats display-test-disable, row clearing, and
shutdown writes. A single display-test-disable command was not reliable on this
hardware.

For orientation, keep `block_orientation = -90` and normal module order first.
Use `rotate = 2` if the digits are upside down, `reverse_order = true` if they
read `4,3,2,1`, and other `block_orientation` values only if each block is still
internally rotated.

Two standalone scripts remain in `tools/` for cases where the package itself is suspect:

| Script | Purpose |
| --- | --- |
| [tools/no-ai-matrix-test.py](tools/no-ai-matrix-test.py) | Hand-verified known-good baseline with no dependency on this package. Run it first if anything looks wrong. |
| [tools/gpio_led_test.py](tools/gpio_led_test.py) | Blink an LED on an unrelated GPIO to prove the SoC survived a wiring incident. |

## Tests And Quality

```bash
.venv/bin/python tests/run_tests.py
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The test suite covers geodesic selection, nullable API fields, major-version rejection, invalid positions, cache-aware polling configuration, the overhead radius, arrival-animation triggering, headline/marquee page construction, and fresh/degraded/offline/last-known state transitions.

## API Reference

`reference/` is retained for offline reading of the API shape and the upstream `luma.led_matrix` source. It is **not** needed at runtime: the application only issues HTTPS GET requests to the public endpoint. Both `reference/` and the zip are gitignored, so they never affect the published repository.

The user-supplied `Seattle_Balc-main.zip` was integrity-checked and extracted to the ignored `reference/Seattle_Balc-main/` directory for local API review. This repository does not republish the friend's dashboard source. The consumer contract is documented publicly at [seattlebalc.com](https://seattlebalc.com/API.md).