# Hardware

Start here if you have forgotten how this thing is put together. This is the
plain-language description of the physical rig: what the parts are, what each one
does, how they connect, and how to prove the whole chain works before blaming the
software. No prior context assumed.

The step-by-step software setup lives in [HUB75 setup on this Pi](HUB75_PI_SETUP.md).
This document is the layer underneath it.

## What Is Plugged In Right Now

A Raspberry Pi 4 fetches aircraft positions over WiFi and draws them onto a
64x64 RGB LED panel. The Pi does not power the panel; a separate 5 V supply does.
The two are tied together by a shared ground and a 16-pin ribbon cable.

```text
  wall socket ──► 5 V supply ──► panel power terminals
                                       │
                                  (shared ground)
                                       │
  WiFi ──► Raspberry Pi 4 ──16-pin ribbon──► panel HUB75 "IN"
```

## Parts

| Part | What it is | Notes |
| --- | --- | --- |
| Raspberry Pi 4 Model B | The computer running this project | Pi 4 or earlier is the well-trodden path for this driver. Pi 5 works through a newer backend but is less proven |
| Waveshare RGB-Matrix-Px-64x64 | The LED panel, 4096 RGB LEDs in a 64x64 grid | 1/32 scan, HUB75 interface, one `IN` port and one `OUT` port. Vendor docs: <https://docs.waveshare.com/RGB-Matrix-Px-64x64/Raspberry-Pi> |
| 16-pin HUB75 ribbon cable | Carries the pixel data from the Pi to the panel | Supplied with the panel. Two 8-pin rows |
| 5 V power supply, 3 A or better | Powers the LEDs, and only the LEDs | The panel is rated 5 V / 3 A, 20 W maximum |
| Panel power lead | Spade or barrel lead from the supply to the panel's power terminals | Supplied with the panel |
| microSD card, Pi power supply, WiFi | Ordinary Pi requirements | The app needs internet access to reach the flights API |

The four MAX7219 8x8 modules this project started on are separate hardware and
are not part of this rig. They are still supported in software; see the
[MAX7219 troubleshooting notes](MAX7219_TROUBLESHOOTING.md).

## Power

This is the part that damages hardware if you get it wrong, so it comes first.

- **Never power the panel from the Pi's 5 V header pins.** A 64x64 panel at full
  white can pull several amps. The Pi header cannot supply that, and trying will
  brown out the Pi, corrupt the SD card, or worse.
- **The panel gets its own regulated 5 V supply**, straight from the supply to the
  panel's power terminals.
- **The supply's ground must be tied to the Pi's ground.** Without a common ground
  the data signals have no shared reference and the panel shows garbage or nothing.
  The ribbon cable carries ground on pin 6, which normally handles this.
- Watch the polarity on the panel's power terminals. They are usually labelled
  `+5V` and `GND`.

A solid white panel is the worst-case current draw, so the colour test described
below is also a genuine test of your power supply. If the picture dims or the Pi
reboots during it, the supply is the problem.

## The Ribbon Cable

The ribbon plugs into the panel connector marked **`IN`**, not `OUT`. `OUT` is for
chaining a second panel onward. Both connectors are keyed, but the key can be
forced, so check the label.

With `hardware_mapping = "regular"` and a single panel, the ribbon lands on these
Pi pins. This is Waveshare's published mapping for the panel, cross-checked
against the driver's `regular` GPIO mapping:

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

What the groups of pins do, in case a single wire needs chasing:

| Group | Purpose |
| --- | --- |
| `R1 G1 B1` | Colour data for the top half of the panel |
| `R2 G2 B2` | Colour data for the bottom half. The panel is driven as two 32-row halves at once |
| `A B C D E` | Row address lines. Five lines select which of 32 row-pairs is lit |
| `CLK` | Clocks each pixel's colour bits into the panel's shift registers |
| `LAT` / `STB` | Latches a completed row so it can be displayed |
| `OE` | Output enable, driven as a fast on/off to control brightness |

Two things worth knowing before you rewire anything:

- **The `E` line is mandatory on this panel.** A 64x64 panel is 1/32 scan and needs
  all five address lines. A 32-row panel only needs `A`–`D`. If `E` is missing or
  loose, half the panel repeats the other half.
- **The panel and the old MAX7219 chain cannot both be connected.** `R1`, `R2`,
  `G2`, `B1`, and `B2` sit on GPIO 11, 8, 9, 7, and 10, which are exactly the SPI0
  pins the MAX7219 chain uses. Move the ribbon and flip `display.panel` in the
  config; do not try to run both.

Direct 3.3 V wiring from the Pi works, and is what this rig does, but it is
technically out of spec for HUB75 inputs. An active level-shifting adapter is the
robust option if you ever see flaky pixels that tuning does not fix. Upstream's
[wiring guide](https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md)
is the authoritative reference, including the HAT and bonnet variants selected
with `hardware_mapping = "adafruit-hat"`.

## The Software Side, Briefly

Three pieces have to line up. Any one of them missing produces a dark panel.

| Piece | What it is | Where |
| --- | --- | --- |
| `rgbmatrix` driver | Compiled C++ extension that bit-bangs the GPIO pins fast enough to refresh the panel | Built into this project's `.venv` from the `RGB-Matrix-Px-xx` checkout |
| This project's venv | The Python environment holding both the driver and the app's dependencies | `.venv` in the repo root |
| `balc.local.toml` | Your local config: coordinates, which panel, panel tuning | Repo root, deliberately not committed |

## Why It Needs `sudo`

Every command that touches the panel must be run as root. This is not optional and
it is not a permissions bug to be worked around.

The driver does not talk to the panel through a kernel device like `/dev/spidev0.0`.
There is no HUB75 kernel driver. Instead it maps the SoC's GPIO registers directly
into its own memory through `/dev/mem` and toggles the pins itself, in a tight loop,
thousands of times a second. That has three consequences:

1. **`/dev/mem` access is root-only.** Mapping physical memory means the process can
   read and write any hardware register on the chip, so the kernel restricts it.
   Without root you get `Permission denied` or `Can't open /dev/mem`.
2. **It needs realtime scheduling priority.** The panel has no frame buffer of its
   own; it only displays what is being clocked into it at that instant. If the
   kernel deschedules the refresh loop for a few milliseconds the picture visibly
   flickers. Raising the process priority requires privilege.
3. **It may need the PWM peripheral**, which is the same hardware the Pi's onboard
   audio uses. That conflict is covered in [HUB75 setup](HUB75_PI_SETUP.md).

The driver gives the privilege back as soon as it is done. With
`hub75.drop_privileges = true`, which is the default and what this rig uses, it
initialises the hardware as root and then drops to an unprivileged user for the
rest of the run. Only the setup is privileged.

### `sudo` And The Virtualenv

`sudo` starts a fresh environment for root, and root has no idea your virtualenv
exists. Activating the venv first does not help, and neither does the `(.venv)`
prompt prefix. So this fails:

```bash
source .venv/bin/activate
sudo python run.py          # ModuleNotFoundError: No module named 'rgbmatrix'
```

Name the venv's interpreter by path instead, which is what every command in these
docs does:

```bash
sudo .venv/bin/python run.py
```

The same rule explains why the driver has to be installed into *this* project's
`.venv` specifically, rather than system-wide or into some other environment.

## Proving The Rig Works

Three checks, in order. Each one rules out a layer, so run them in sequence and
stop at the first failure.

**1. Is the driver installed in the right place?** No hardware involved, no `sudo`.

```bash
cd ~/projects/new/balcFlights-LED
.venv/bin/python -c "import rgbmatrix; print(rgbmatrix.__file__)"
```

The printed path must be inside this project's `.venv`. If it errors, reinstall the
driver as described in [HUB75 setup](HUB75_PI_SETUP.md).

**2. Do the wiring and power work?** This floods the panel white, red, green, then
blue.

```bash
sudo .venv/bin/python tests/run_tests.py --matrix-only --phase wiring
```

| What you see | What it means |
| --- | --- |
| Clean solid fills | Wiring and power are good |
| Nothing at all | Ribbon seating, panel power, or the `IN` versus `OUT` connector |
| Colours in the wrong order | `hub75.led_rgb_sequence` |
| Top and bottom halves identical | The `E` address line is not connected |
| Dimming, flicker, or the Pi rebooting on white | Power supply |
| Ghosting or torn rows | Raise `hub75.gpio_slowdown` |

**3. Does the application draw?**

```bash
sudo .venv/bin/python run.py
```

`Ctrl+C` stops it and blanks the panel. For the radar specifically, driven by
synthetic traffic so it works at 3am with an empty sky:

```bash
sudo .venv/bin/python tests/run_tests.py --matrix-only --phase radar
```

If step 2 passes but step 3 does not, the fault is in this project or its config,
not the hardware. To confirm that independently, the vendor's own sample scripts
drive the panel with none of this project's code involved:

```bash
cd ~/projects/new/RGB-Matrix-Px-xx/example/Rasberry-Pi/bindings/python/samples
sudo ~/.venvs/rgbmatrix/bin/python rotating-block-generator.py \
  --led-rows=64 --led-cols=64 --led-chain=1 \
  --led-slowdown-gpio=4 --led-no-hardware-pulse=1
```

## Starting Over From Nothing

If the SD card is reflashed, or this has to be rebuilt on another Pi:

1. Wire the panel per the table above. Panel power from its own 5 V supply, ground
   shared with the Pi.
2. Install the build tools: `sudo apt install -y git build-essential python3-dev python3-venv cython3`
3. Clone this repo, create `.venv`, install it, and copy `balc.example.toml` to
   `balc.local.toml`. See the README's Setup section.
4. Build the `rgbmatrix` driver into that same `.venv`. See
   [HUB75 setup](HUB75_PI_SETUP.md).
5. Set `display.panel = "hub75"` and the `[hub75]` block in `balc.local.toml`.
6. Work through the three checks above.

No SPI is needed for the HUB75 panel; it drives GPIO directly. SPI only matters if
you go back to the MAX7219 chain.
