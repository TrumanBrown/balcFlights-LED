# balcFlights-LED

[![CI](https://github.com/TrumanBrown/balcFlights-LED/actions/workflows/ci.yml/badge.svg)](https://github.com/TrumanBrown/balcFlights-LED/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

Display the aircraft currently overhead on an LED matrix attached to a Raspberry Pi 4. Two panels are supported and either can be selected with one config line:

| `display.panel` | Hardware | Geometry |
| --- | --- | --- |
| `max7219` | Four daisy-chained MAX7219 8x8 modules on hardware SPI | 32x8 monochrome |
| `hub75` | HUB75 RGB panel driven by rpi-rgb-led-matrix, e.g. the Waveshare RGB-Matrix-P2.5-64x64 | 64x64 full colour |

The application consumes the public, read-only [Seattle Balc Flights API](https://seattlebalc.com/api), computes great-circle distance and bearing from a configured reference point, and lays the result out to fit whichever panel is attached.

> **Attribution.** [seattlebalc.com](https://seattlebalc.com/) is a third-party service that this project is not affiliated with, endorsed by, or maintained by. This repository is an independent client that only issues HTTPS GET requests to that documented public endpoint. No API key is required, and responses are cached upstream for 20 seconds, so the polling interval is floored at 20 seconds to avoid aggressive requests. If the API changes or goes away, this project stops working. Point `api.endpoint` at any service that returns the same contract.

## Contents

- [What The Matrix Shows](#what-the-matrix-shows)
- [MAX7219 Chain](#max7219-chain)
- [HUB75 Panels](#hub75-panels)
- [Setup](#setup)
- [Configuration](#configuration)
- [Run](#run)
- [Hardware Checks](#hardware-checks)
- [Project Structure](#project-structure)
- [Tests And Quality](#tests-and-quality)
- [License](#license)

## What The Matrix Shows

On the MAX7219 chain the callsign of the nearest aircraft occupies the left 24 columns. The rightmost 8x8 block is reserved for a single arrow that points from the reference location to that aircraft.

```text
A S A 1 2 3 |>|      callsign (24px) + bearing arrow (8x8 block)
###########..        proximity bar (row 7, callsign area)
```

| Element | Where | Behaviour |
| --- | --- | --- |
| Callsign | Columns 0-23 | Always visible. Registration or ICAO identifier when there is no callsign. Clipped rather than allowed to reach the arrow. |
| Bearing arrow | Columns 24-31, rows 0-6 | Points from your configured location toward the aircraft, snapped to the nearest of eight compass directions. |
| Proximity bar | Row 7, columns 0-23 | Longer means closer. Full width is directly overhead, empty is the edge of the search radius. |
| Overhead marker | Arrow block | The arrow blinks while the aircraft is inside `location.overhead_radius_nautical_miles`. |
| Stale marker | Bottom-right pixel | Lit when the data is last-known rather than live. |
| Detail scroll | Full width | Once per cycle: `ASA123 B739 2.4NM SE 5500FT CLB 266KT`. Climb, level, and descent are reported here. |
| Arrival animation | Full width | When the nearest aircraft *changes*, a plane sprite flies past, then the new callsign is revealed column by column. |
| Idle | Full width | Drifting dots alternating with `NO FLT` when no aircraft qualifies. |

The arrow is drawn from a table of hand-designed sprites, one per compass octant, rather than by rotating a line. At eight pixels across, a rounded arbitrary-angle vector degrades into scattered dots and reads as noise, so direction is quantised to 45° and each direction gets a shape chosen to be unmistakable. That constraint is specific to an 8x8 block: on a HUB75 panel the arrow is drawn as a real rotated vector at the exact bearing.

Status text such as `OFFLINE` has no bearing to show, so those frames use the full 32 columns instead of reserving the arrow block.

Upstream failures are not presented as quiet airspace. A recent last-known aircraft is marked stale, and expired data becomes an explicit `DATA?` or `OFFLINE` state.

### On A HUB75 Panel

A 64x64 panel is tall enough for a stacked layout instead of a single strip, so the same frames are re-laid-out rather than letterboxed. Every element scales from the reported panel size, so 64x32 and chained panels work too.

```text
   A S A 1 2 3      callsign, scaled 2x, centred on the top band
      /##\
     /####\         bearing arrow, rotated to the exact bearing
       ##
 ##########....     full-width proximity bar on the bottom rows
```

| Element | Where | Behaviour |
| --- | --- | --- |
| Callsign | Top band | Scaled up by `height / 32`, centred, clipped rather than wrapped. Amber instead of white when the data is stale. |
| Bearing arrow | Middle band | A filled vector arrow rotated to the true bearing, sized to the largest square that fits between the callsign and the bar. Amber while overhead, cyan otherwise, and it blinks off in the overhead frames. |
| Proximity bar | Bottom rows | Full panel width. Green, then amber, then red as the aircraft closes in. |
| Stale marker | Top-right corner | A small amber square. |
| Detail scroll | Vertically centred | The same detail line, scrolled at the scaled font size. |
| Arrival animation | Full panel | The plane sprite, scaled, then the new page revealed column by column. |

A 64x64 panel has room to resolve a real angle, so the bearing is not rounded into one of eight sprites the way it must be inside a single 8x8 MAX7219 block. Below a 16-pixel arrow box the vector degrades and the layout falls back to the octant sprites, so short panels still read clearly. The stacked layout assumes at least 32 rows; it stays on-panel below that, but the bands get cramped.

### Staying Current Between Polls

The API advertises `Cache-Control: public, max-age=20`, asks consumers not to poll aggressively, and exposes no `ETag`, so conditional requests are not possible and every poll is a full transfer. Polling harder would therefore cost bandwidth without buying freshness.

Instead, each flight carries a `position.projected` estimate produced by advancing its last observed fix along its reported ground speed and heading. This project uses that projection as the starting point and then **continues the dead reckoning locally**, recomputing distance and bearing on every page rather than only on every fetch. The result is an arrow that keeps tracking between requests.

Local extrapolation honours the same 45-second ceiling the API applies to its own projection, and never extrapolates an aircraft that is on the ground or missing speed or heading. Aircraft also age out mid-window: once the elapsed time pushes a flight past `maximum_seen_seconds`, it stops being a candidate without waiting for the next poll.

A projected position is dead reckoning, not a new observation. It is the right basis for pointing an arrow, and the wrong basis for anything requiring source provenance.


Set `display.animations = false` to suppress the arrival sprite and show content changes immediately.

### Fonts

`display.font` selects the callsign font. The renderer measures which rows the font inks, lifts the glyphs to the top, and puts the proximity bar in the rows left over. The callsign always has 24 columns, because the arrow block is reserved regardless of font.

| Font | `ASA123` | `QXE2372` | Rows inked | Leaves a bar row |
| --- | ---: | ---: | ---: | --- |
| `atari` (default) | 24 px | 28 px | 6 | yes |
| `tiny` | 24 px | 28 px | 5 | yes |
| `lcd` | 34 px | 42 px | 8 | no |
| `cp437` | 42 px | 51 px | 8 | no |
| `sinclair` | 41 px | 49 px | 8 | no |

`atari` and `tiny` both fit a six-character callsign in exactly 24 px, but `atari` uses six rows rather than five, so it is markedly easier to read. Anything longer, and any wider font, is clipped at the arrow boundary. The detail scroll always uses `cp437`, because a marquee has unlimited width.

The widths above are the limits on a 32-column MAX7219. A 64x64 HUB75 panel scales the same fonts up by 2x and has twice the columns, so every font fits a full callsign there.

## MAX7219 Chain

The MAX7219 display is four daisy-chained 8x8 modules, giving a 32x8 monochrome matrix on hardware SPI0/CE0. This profile is **verified working on a Raspberry Pi 4 Model B**:

```toml
[display]
panel = "max7219"

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

[tools/matrix_baseline.py](tools/matrix_baseline.py) is the hand-verified baseline that established this configuration. It uses luma's default bus speed and contrast rather than the values above; both work. Any driver change must still pass that script.

Pin mapping for SPI0/CE0:

| MAX7219 module | Pi signal | BCM | Physical pin |
| --- | --- | ---: | ---: |
| `DIN` | SPI0 MOSI | GPIO10 | 19 |
| `CLK` | SPI0 SCLK | GPIO11 | 23 |
| `CS` / `LOAD` | SPI0 CE0 | GPIO8 | 24 |
| `GND` | Ground | - | 6 or another ground pin |
| `VCC` | 5V supply | - | 2 or 4 |

Four MAX7219 boards must not be treated like a single low-current Pi accessory. Use a regulated external 5 V supply with adequate current capacity and connect its ground to Pi ground. The Pi's 3.3 V DIN, CLK, and CS/LOAD outputs are below the MAX7219's guaranteed input-high threshold; a `74AHCT125` or equivalent 5 V-powered buffer removes that margin problem. Add local 100 nF ceramic and 10 uF bulk decoupling near the matrix chain.

`spi_speed_hz` accepts 500000, 1000000, 2000000, 4000000, or 8000000. The shipped default stays at the conservative 500 kHz, because it buys the timing margin a level shifter would otherwise provide and nothing about another builder's wiring can be assumed. 1 MHz is verified clean on the reference build and is a safe first step up. Higher clocks are exactly where unbuffered 3.3 V signalling starts to fail, so raise it empirically rather than optimistically:

```bash
.venv/bin/python tests/run_tests.py --matrix-only --phase speed
```

That opens the bus once per supported speed, draws static text and a scroll at each, and closes it again. Watch for flicker, dropped blocks, or garbled glyphs, then set `matrix.spi_speed_hz` to the fastest rate that stayed clean. Faster clocks buy smoother scrolling and animation, not extra data.

See [MAX7219 hardware troubleshooting](docs/MAX7219_TROUBLESHOOTING.md) for the diagnostic history and a pin-by-pin recovery procedure.

## HUB75 Panels

`display.panel = "hub75"` drives a HUB75 RGB panel instead. The shipped defaults describe a Waveshare RGB-Matrix-P2.5-64x64 (64x64, 1/32 scan, HUB75 in and out) wired straight to the Pi GPIO header:

```toml
[display]
panel = "hub75"

[hub75]
rows = 64
columns = 64
chain_length = 1
parallel = 1
hardware_mapping = "regular"
gpio_slowdown = 4
pwm_bits = 11
pwm_lsb_nanoseconds = 130
brightness = 50
limit_refresh_rate_hz = 0
led_rgb_sequence = "RGB"
panel_type = ""
pixel_mapper_config = ""
disable_hardware_pulsing = false
drop_privileges = true
```

Those values map one-to-one onto `RGBMatrixOptions` in [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix), so upstream's documentation applies unchanged. Chained or multi-row setups only need `chain_length` and `parallel`; the layout derives every band from the resulting panel size.

### Driver Install

The Python bindings are not published to PyPI, but the upstream repository is pip-installable, which builds them against the interpreter you point at it:

```bash
sudo apt install -y python3-dev cython3
.venv/bin/python -m pip install "git+https://github.com/hzeller/rpi-rgb-led-matrix"
```

Install it into the same virtualenv that runs `run.py`. If it is missing, the app fails at startup with an explicit message rather than a blank panel. Upstream added Raspberry Pi 5 support recently through its RP1 backends, but the mature, well-trodden path is a Pi 4 or earlier; this project is verified on a Pi 4 Model B.

### Onboard Audio Conflicts With The Panel

The driver generates its pulses with the same PWM peripheral as the Pi's onboard sound, and it refuses to start while `snd_bcm2835` is loaded. Blacklisting audio is the better fix, because hardware pulsing is what keeps the picture stable:

```bash
echo "blacklist snd_bcm2835" | sudo tee /etc/modprobe.d/blacklist-rgb-matrix.conf
sudo update-initramfs -u
sudo reboot
```

Waveshare's own quick-start passes `--led-no-hardware-pulse` instead, which is the same thing as setting `hub75.disable_hardware_pulsing = true`. That works without touching the audio driver, at the cost of a less stable picture. This project checks for the module before opening the panel and tells you which of the two fixes to apply, rather than letting the driver terminate the process.

### Wiring And Power

The panel is specified at 5 V/3 A, 20 W maximum, so give it its own regulated supply and tie that supply's ground to Pi ground. Do not power a 64x64 panel from the Pi header. The `wiring` hardware phase floods the whole panel white, which is the worst-case current draw and therefore a real test of the supply.

With `hardware_mapping = "regular"` and a single panel, the ribbon lands on these pins. This table is Waveshare's published mapping for this panel cross-checked against the library's `regular` GPIO mapping:

| HUB75 | BCM | Physical | HUB75 | BCM | Physical |
| --- | ---: | ---: | --- | ---: | ---: |
| `R1` | 11 | 23 | `R2` | 8 | 24 |
| `G1` | 27 | 13 | `G2` | 9 | 21 |
| `B1` | 7 | 26 | `B2` | 10 | 19 |
| `A` | 22 | 15 | `B` | 23 | 16 |
| `C` | 24 | 18 | `D` | 25 | 22 |
| `E` | 15 | 10 | `CLK` | 17 | 11 |
| `LAT`/`STB` | 4 | 7 | `OE` | 18 | 12 |
| `GND` | - | 6 | | | |

Two consequences worth noting before wiring anything:

- **The two panels cannot share the Pi.** `R1`, `R2`, `G2`, `B1`, and `B2` sit on GPIO 11, 8, 9, 7, and 10, which are exactly the SPI0 pins the MAX7219 chain uses. Move the ribbon and flip `display.panel`.
- **The `E` address line is mandatory here.** A 64x64 panel is 1/32 scan and needs all five address lines. The `regular` mapping puts `E` on GPIO 15; the first-generation Adafruit HAT needs a solder bridge for it.

Upstream's [wiring guide](https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md) is the authoritative reference, including the HAT and bonnet variants selected with `hardware_mapping = "adafruit-hat"`. Direct 3.3 V wiring works but is out of spec for HUB75 inputs; an active level-shifting adapter is the robust option, exactly as with the MAX7219 chain.

### Tuning

| Setting | When to change it |
| --- | --- |
| `gpio_slowdown` | Raise it if rows ghost, flicker, or show noise; lower it for a higher refresh rate. A Pi 4 is fast enough to overrun panels, so 4 is the starting point here. |
| `panel_type` | Set `FM6126A` or `FM6127` only if the panel never lights up at all. Those chipsets need an init sequence; a plain HUB75 panel needs none. |
| `led_rgb_sequence` | Only if the `wiring` phase shows the wrong solid colours. That is a panel property, not a layout bug. |
| `brightness` | Lower it to cut current draw and heat. 50 is already half power. |
| `limit_refresh_rate_hz` | Pin the refresh rate when background load causes visible brightness fluctuation. |

The driver needs root for the timing registers, so the live display is started with `sudo`. Keep `drop_privileges = true`: the library then drops back to an unprivileged user as soon as the panel is initialised, so the polling loop does not run as root.

```bash
sudo .venv/bin/python run.py --panel hub75
```

## Setup

Requires Python 3.11+ and an SPI-enabled Raspberry Pi (`sudo raspi-config` → Interface Options → SPI). Enable SPI before installing, and add your user to the `spi` group if `/dev/spidev0.0` is not readable. SPI is only needed for the MAX7219 chain; a HUB75 panel drives GPIO directly and needs the extra driver described in [HUB75 Panels](#hub75-panels).

```bash
git clone https://github.com/TrumanBrown/balcFlights-LED.git
cd balcFlights-LED
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp balc.example.toml balc.local.toml
```

`balc.local.toml`, `.venv`, and the local `reference/` tree are intentionally ignored by Git, so your own coordinates are never committed.

## Configuration

The shipped default reference point is the API's own published center at `47.6175, -122.305`. Set your own vantage point in `balc.local.toml`, which is gitignored so a personal location never reaches version control. Environment variables override both:

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
BFL_PANEL
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
BFL_HUB75_ROWS
BFL_HUB75_COLUMNS
BFL_HUB75_CHAIN
BFL_HUB75_PARALLEL
BFL_HUB75_MAPPING
BFL_HUB75_GPIO_SLOWDOWN
BFL_HUB75_PWM_BITS
BFL_HUB75_PWM_LSB_NS
BFL_HUB75_BRIGHTNESS
BFL_HUB75_LIMIT_REFRESH_HZ
BFL_HUB75_RGB_SEQUENCE
BFL_HUB75_PANEL_TYPE
BFL_HUB75_PIXEL_MAPPER
BFL_HUB75_NO_HARDWARE_PULSE
BFL_HUB75_DROP_PRIVILEGES
```

The refresh interval defaults to 20 seconds and cannot be set lower, because the public API advertises `max-age=20` and asks consumers not to poll aggressively. Positions are extrapolated locally between polls, so a longer interval costs accuracy only once the 45-second projection ceiling is reached. Aircraft reported on the ground or older than `maximum_seen_seconds` are excluded by default. `overhead_radius_nautical_miles` defaults to 1.5, must be greater than zero, and can be no larger than the search radius. Widen it and the blink stops meaning much, since a large share of Seattle traffic passes within a few miles.

`scroll_delay` controls the detail marquee, `frame_seconds` controls the arrival and idle animations. Both trade smoothness against the available SPI bandwidth.

## Run

One file starts the live display:

```bash
.venv/bin/python run.py
```

That polls the API every 20 seconds and drives the matrix until you press Ctrl+C, which blanks it. Nothing else needs to be running.

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

`display.panel` decides which physical display `matrix` means, and `--panel` overrides it for one run:

```bash
.venv/bin/python run.py --panel max7219
sudo .venv/bin/python run.py --panel hub75
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

The hardware phases follow `display.panel`. On the MAX7219 chain that runs four phases in order and always blanks the chain on exit:

| Phase | What it proves |
| --- | --- |
| `wiring` | Raw display-test register toggle: dark, every LED on, dark. Proves VCC/GND/DIN/CLK/CS. |
| `blocks` | Lights each 8x8 block in turn. Proves `matrix.cascaded`. |
| `visuals` | Every frame the application can draw, including all eight arrow directions, the arrival animation, and idle drift. |
| `off` | Clears every row and enters shutdown. |

On a HUB75 panel there is no cascade to count and no SPI clock to step, so `blocks` and `speed` are skipped and `wiring` becomes a colour test:

| Phase | What it proves |
| --- | --- |
| `wiring` | Solid white, red, green, then blue fills. White is also the panel's worst-case current draw, so it doubles as a power-supply test. Wrong colours mean `hub75.led_rgb_sequence`; missing rows or ghosting mean `hub75.gpio_slowdown` or the supply. |
| `visuals` | The same frame sweep, laid out for the panel. |
| `off` | Clears the panel. |

One further MAX7219 phase is opt-in, because it opens and closes the bus once per speed and so cannot share a device with the others:

| Phase | What it proves |
| --- | --- |
| `speed` | Steps `spi_speed_hz` through every supported rate so you can see which stay clean. |

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
| [tools/matrix_baseline.py](tools/matrix_baseline.py) | Hand-verified known-good baseline with no dependency on this package. Run it first if anything looks wrong. |
| [tools/gpio_led_test.py](tools/gpio_led_test.py) | Blink an LED on an unrelated GPIO to prove the SoC survived a wiring incident. |

## Project Structure

```text
src/balc_flights_led/
  api.py           HTTPS client and strict parser for the public flight feed
  config.py        TOML + environment configuration with validation
  models.py        Coordinates, Flight, BoundingBox, NearestFlight
  selection.py     Great-circle distance, bearing, bounding box, nearest pick
  service.py       Polling loop, staleness, and fresh/degraded/offline states
  presentation.py  Renderer-independent frames: headline, marquee, animations
  display.py       MAX7219, HUB75, and console renderers
  cli.py           Argument parsing and entry point
run.py             Convenience launcher for the live display
tools/             Standalone hardware scripts, independent of the package
tests/             Unit tests plus the run_tests.py hardware phase runner
docs/              Hardware troubleshooting notes
```

Presentation is deliberately separated from rendering: `presentation.py` produces frames as plain data, so the console and matrix renderers stay interchangeable and the visuals are testable without hardware.

## Tests And Quality

```bash
.venv/bin/python tests/run_tests.py
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The test suite covers geodesic selection, nullable API fields, major-version rejection, invalid positions, cache-aware polling configuration, the overhead radius, arrival-animation triggering, headline/marquee page construction, fresh/degraded/offline/last-known state transitions, and both panel layouts rendered offscreen.

## API Reference

The upstream contract is documented publicly at [seattlebalc.com/api](https://seattlebalc.com/api). This client targets API major version 1 and rejects any other major version rather than guessing at an unknown schema.

A local `reference/` directory is gitignored and used only for offline reading of the upstream `luma.led_matrix` source. It is **not** needed at runtime and is never published here; the application only issues HTTPS GET requests to the configured endpoint.

## License

Released under the [MIT License](LICENSE).

This project is not affiliated with seattlebalc.com, Alaska Airlines, or any other operator whose flights it displays. Aircraft data originates from third-party ADS-B sources and is provided without warranty. It is intended for hobbyist and informational use, and must not be relied upon for navigation, flight safety, or any operational decision.