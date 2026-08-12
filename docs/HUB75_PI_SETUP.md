# HUB75 Setup On This Pi

Verified working end to end on 2026-08-11: the live flight display renders on the
panel, driven by this project's own `Hub75Renderer`.

This project was originally built for a MAX7219 chain (32x8, SPI, `luma.led_matrix`).
That path still works and is still selectable. This document covers the current
hardware — a Waveshare RGB-Matrix-Px-64x64 HUB75 panel on the GPIO header — and
records exactly what makes it work here, so it can be rebuilt from scratch without
rediscovering any of it.

## Verified environment

| Item | Value |
| --- | --- |
| Board | Raspberry Pi 4 Model B Rev 1.5 |
| OS | Debian 12 (bookworm), aarch64, kernel 6.12.93 |
| Panel | Waveshare RGB-Matrix-Px-64x64, 64x64, 1/32 scan, wired straight to the GPIO header |
| Panel power | Its own regulated 5 V supply, ground tied to Pi ground |
| Project | `/home/truman/projects/new/balcFlights-LED` |
| Project venv | `.venv` (Python 3.11.2) — **the one that matters** |
| Driver | `rgbmatrix 0.0.1+20260125`, built into the project venv |
| Driver source | `/home/truman/projects/new/RGB-Matrix-Px-xx/example/Rasberry-Pi` |

Vendor documentation for the panel:
<https://docs.waveshare.com/RGB-Matrix-Px-64x64/Raspberry-Pi>

## The driver dependency

`rgbmatrix` is a compiled C++ extension. It is not on PyPI and it is **not** a
normal dependency in `pyproject.toml` — it has to be built from a source checkout
against the exact interpreter that will import it.

The Waveshare fork lives in a sibling checkout:

```
/home/truman/projects/new/RGB-Matrix-Px-xx/example/Rasberry-Pi
```

Install or reinstall it into this project's venv:

```bash
cd ~/projects/new/balcFlights-LED
.venv/bin/python -m pip install ~/projects/new/RGB-Matrix-Px-xx/example/Rasberry-Pi
```

Verify it landed in the right place — the printed path must be inside **this**
project's `.venv`:

```bash
.venv/bin/python -c "import rgbmatrix; print(rgbmatrix.__file__)"
# /home/truman/projects/new/balcFlights-LED/.venv/lib/python3.11/site-packages/rgbmatrix/__init__.py
```

There is a second, unrelated venv at `~/.venvs/rgbmatrix`. It exists only for
running the vendor's sample scripts (see [Isolating a fault](#isolating-a-fault)).
This project does not use it, and `.venv/pyvenv.cfg` has
`include-system-site-packages = false`, so nothing leaks in from outside.

## Running it

The driver needs root for `/dev/mem` and realtime scheduling. Root does not
inherit a virtualenv, so the venv interpreter must be named by path:

```bash
cd ~/projects/new/balcFlights-LED
sudo .venv/bin/python run.py
```

`balc.local.toml` already has `display.panel = "hub75"`, so no flag is needed.
To force one or the other for a single run:

```bash
sudo .venv/bin/python run.py --panel hub75
sudo .venv/bin/python run.py --panel max7219
```

Console-only, no hardware touched — useful for logic work away from the Pi:

```bash
.venv/bin/python run.py --renderer console
```

`Ctrl+C` stops it and blanks the panel.

The panel shows the radar: a detail block for the nearest aircraft above a dial
plotting every aircraft in range. When a different aircraft becomes the closest,
a plane sprite flies across the panel and the dial is wiped in behind it. To
confirm all of that without waiting for real traffic:

```bash
sudo .venv/bin/python tests/run_tests.py --matrix-only --phase radar
```

## Configuration that works here

In `balc.local.toml`. These are not guesses; they are the values the panel runs on.

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
brightness = 50
disable_hardware_pulsing = true
drop_privileges = true
```

Two of those matter more than the rest:

* **`gpio_slowdown = 4`** — a Pi 4 clocks GPIO faster than this panel can latch.
  4 is stable here. Lower it toward 2 for a higher refresh rate, but back off the
  moment rows start ghosting or flickering.
* **`disable_hardware_pulsing = true`** — `snd_bcm2835` (onboard audio) is loaded
  on this Pi and claims the same PWM peripheral the driver wants. Without this the
  app refuses to start with an explanatory error. The alternative, which gives a
  more stable picture, is to blacklist the audio module and set this back to
  `false`:

  ```bash
  echo "blacklist snd_bcm2835" | sudo tee /etc/modprobe.d/blacklist-rgb-matrix.conf
  sudo update-initramfs -u
  sudo reboot
  ```

Startup also prints a suggestion to add `isolcpus=3` to `/boot/cmdline.txt`. It is
optional; it dedicates a core to the refresh loop and reduces flicker under load.

## Translating the Waveshare docs

Waveshare's quick-start uses command-line flags on the sample scripts. This project
takes the same settings from TOML. The mapping is one-to-one:

| Waveshare flag | `[hub75]` key |
| --- | --- |
| `--led-rows=64` | `rows = 64` |
| `--led-cols=64` | `columns = 64` |
| `--led-chain=1` | `chain_length = 1` |
| `--led-parallel=1` | `parallel = 1` |
| `--led-gpio-mapping=regular` | `hardware_mapping = "regular"` |
| `--led-slowdown-gpio=4` | `gpio_slowdown = 4` |
| `--led-no-hardware-pulse` | `disable_hardware_pulsing = true` |
| `--led-brightness=50` | `brightness = 50` |
| `--led-pwm-bits=11` | `pwm_bits = 11` |
| `--led-limit-refresh=0` | `limit_refresh_rate_hz = 0` |
| `--led-rgb-sequence=RGB` | `led_rgb_sequence = "RGB"` |
| `--led-pixel-mapper="Rotate:180"` | `pixel_mapper_config = "Rotate:180"` |
| `--led-panel-type=FM6126A` | `panel_type = "FM6126A"` |
| `--led-no-drop-privs` | `drop_privileges = false` |

Everything in `[hub75]` is passed straight through to `RGBMatrixOptions`, so
upstream's documentation applies unchanged.

## Isolating a fault

When the panel misbehaves, first decide whether it is this project or the hardware.
The vendor's sample scripts drive the panel with no application code involved:

```bash
cd ~/projects/new/RGB-Matrix-Px-xx/example/Rasberry-Pi/bindings/python/samples
sudo ~/.venvs/rgbmatrix/bin/python rotating-block-generator.py \
  --led-rows=64 --led-cols=64 --led-chain=1 \
  --led-slowdown-gpio=4 --led-no-hardware-pulse=1
```

* Sample works, app does not → the problem is in this project or its config.
* Sample also fails → wiring, power, or driver install.

That checkout has its own notes at
`RGB-Matrix-Px-xx/example/Rasberry-Pi/bindings/python/samples/README.md`.

To test just this project's driver path, without the flight logic:

```bash
cd ~/projects/new/balcFlights-LED
sudo .venv/bin/python -c "
import time
from pathlib import Path
from balc_flights_led.config import load_settings
from balc_flights_led.display import open_hub75
s = load_settings(Path('balc.local.toml'))
m = open_hub75(s.hub75)
print('opened', m.width, 'x', m.height)
for y in range(m.height):
    for x in range(m.width):
        m.SetPixel(x, y, 255, 255, 255)
time.sleep(2)
m.Clear()
"
```

A full white panel is also the worst-case current draw, so it doubles as a real
test of the power supply.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'rgbmatrix'` | Bindings are not in `.venv`, or you ran a different interpreter. Reinstall as above and check the path |
| `HUB75 panels need the rpi-rgb-led-matrix Python bindings` | Same cause, reported by the app's own check |
| `snd_bcm2835 is loaded and the HUB75 driver needs the same PWM hardware` | Set `disable_hardware_pulsing = true`, or blacklist onboard audio |
| `Permission denied` / `Can't open /dev/mem` | Missing `sudo` |
| Rows ghost, flicker, or tear | Raise `gpio_slowdown`; add `limit_refresh_rate_hz = 100`; consider `isolcpus=3` |
| The whole picture freezes for about a second, then jumps | The API poll used to run on the render thread. Measured at 0.5-0.9 s per fetch on this Pi, so the panel held its last frame that long every interval. Fixed: the poll runs on its own thread and the renderer keeps drawing from the cached feed. If it comes back, the stall is elsewhere in the render loop |
| The picture freezes for several seconds, occasionally much longer | Network, not the panel. `api.timeout_seconds` bounds the socket, but nothing bounds `getaddrinfo`, so a sick resolver can stall a fetch well past it. That no longer stops the display, only the data behind it; the console log shows the gap between `INFO` lines |
| Brief tearing or a stutter under load | The refresh loop is competing for a core. `isolcpus=3`, `limit_refresh_rate_hz`, or blacklisting `snd_bcm2835` so hardware pulsing can be re-enabled |
| Panel dims or the Pi resets under bright frames | Power. The panel needs its own 5 V supply, never the Pi header |
| Colours wrong | `led_rgb_sequence = "RBG"` or another permutation |
| Nothing lights at all | Recheck the 16-pin HUB75 ribbon and panel power. Only if that is sound, try `panel_type = "FM6126A"` |
| Image rotated or mirrored | `pixel_mapper_config = "Rotate:180"` |
| MAX7219 problems | Different hardware entirely, see [MAX7219 troubleshooting](MAX7219_TROUBLESHOOTING.md) |

## Rebuilding after a driver change

Editing the C++ or Cython sources in the `RGB-Matrix-Px-xx` checkout does nothing
until the extension is rebuilt and reinstalled:

```bash
cd ~/projects/new/balcFlights-LED
.venv/bin/python -m pip install --force-reinstall --no-deps \
  ~/projects/new/RGB-Matrix-Px-xx/example/Rasberry-Pi
```
