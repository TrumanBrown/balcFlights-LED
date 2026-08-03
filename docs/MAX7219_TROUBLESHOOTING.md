# MAX7219 Hardware Troubleshooting

Last investigated: 2026-07-24
Last confirmed working: 2026-08-02

## Current Status: Working

The 32x8 chain renders text, scrolls messages, and blanks reliably on SPI0/CE0. The configuration that established this is [tools/no-ai-matrix-test.py](../tools/no-ai-matrix-test.py):

```python
serial = spi(port=0, device=0, gpio=noop())
device = max7219(serial, cascaded=4, block_orientation=-90, blocks_arranged_in_reverse_order=False)
```

That script leaves `bus_speed_hz` and `contrast` at luma's defaults (8 MHz, `0x70`). The application's committed profile is deliberately more conservative at 500 kHz and contrast 64, and works equally well. Treat the script as the reference: if the application misbehaves but that script does not, the fault is in application code, not wiring.

Notes on the earlier failures:

- `block_orientation` accepts only `0`, `90`, `-90`, `180`. Passing `-180` raises a bare `AssertionError` inside `luma/led_matrix/device.py`.
- `ImageFont.truetype("examples/pixelmix.ttf", 8)` appears in upstream luma examples and only resolves inside a checkout of `luma.examples`. Use the bundled bitmap fonts from `luma.core.legacy.font` (`TINY_FONT`, `LCD_FONT`, `CP437_FONT`) instead; they need no external files and are sized for 8-pixel rows.
- A single display-test-disable write did not reliably blank the chain. The repeated blanking sequence is retained for that reason.

## Electrical Hardening

Upstream Luma documentation warns that:

- More than one or two matrices should use a separate regulated 5 V supply with Pi and matrix grounds connected.
- Pi SPI outputs are 3.3 V, outside the MAX7219's guaranteed 5 V input tolerance, and direct drive causes intermittent behavior.
- DIN, CS/LOAD, and CLK should be level-shifted to 5 V.
- In a chain of separate boards, only DOUT-to-DIN is serial; CLK, CS/LOAD, VCC, and ground should be distributed reliably to every board.

Source: [Luma LED matrix notes](https://luma-led-matrix.readthedocs.io/en/latest/notes.html)

These remain worth doing even though the chain currently works. The 500 kHz clock buys margin that a level shifter would otherwise provide.

## Historical Investigation

Verified while the chain was believed faulty. Still useful if the display regresses.

- Pi model: Raspberry Pi 4 Model B Rev 1.5.
- Kernel: `6.12.93+rpt-rpi-v8`.
- SPI controller and `spidev` modules load without errors.
- `/dev/spidev0.0` maps to SPI0 CE0 and `/dev/spidev0.1` maps to CE1.
- BCM10 is SPI0 MOSI, BCM11 is SPI0 SCLK, and BCM8 is kernel-owned CE0, idle high.
- No background process holds or rewrites either SPI device.
- The Pi reports no undervoltage or throttling history.
- The legacy and current Luma versions have equivalent MAX7219 and SPI implementations.
- The unchanged legacy script and the new driver both complete without software errors.
- CE0 at 500 kHz visibly controls the display-test register: the matrix goes dark and then lights every LED.
- A single terminal display-test-disable/clear/shutdown sequence did not turn the matrix off.
- Ten repeated display-test-disable/row-zero/shutdown sequences reliably turned it off and kept it dark.
- CE1 and earlier CE0 attempts produced inconsistent observations before the repeatable bus test isolated the final-phase issue.
- A separate slow software-SPI implementation toggled BCM10/11/8 directly and sent ten full clear/shutdown cycles. Hardware SPI pin modes were restored afterward.
- A reboot did not fix the unreliable one-shot behavior.

There is no MAX7219 readback connection, so a successful Linux write only proves bytes reached the Pi's GPIO peripheral. It cannot prove continuity, voltage, or signal quality at the matrix input header.

## Reliability Wiring Check

Power the Pi and matrix down before moving wires. Verify against the matrix's **input** header, not its output header:

| Matrix input | Raspberry Pi | Physical pin |
| --- | --- | ---: |
| `VCC` | Regulated 5 V supply | Supply-dependent |
| `GND` | Supply ground and Pi ground | Pi pin 6 is one option |
| `DIN` | Level-shifted GPIO10 / MOSI | 19 |
| `CS` or `LOAD` | Level-shifted GPIO8 / CE0 | 24 |
| `CLK` | Level-shifted GPIO11 / SCLK | 23 |

Use a multimeter continuity test with power removed. Also verify that the external 5 V supply ground and Pi ground are actually common.

For logic conversion, prefer a `74AHCT125`, `74HCT125`, or another buffer whose 5 V-powered input specification accepts a 3.3 V high. Shift DIN, CLK, and CS/LOAD. Avoid assuming a generic 5 V CMOS buffer accepts 3.3 V as high.

Provide local decoupling at the matrix: at least 100 nF ceramic plus 10 uF bulk capacitance near the MAX7219 chain. Keep DIN, CLK, CS/LOAD, and ground leads short. Start with low display contrast.

## Test Order

1. Power-cycle the matrix supply, not merely Linux. The MAX7219 has no reset pin.
2. Run the known-good baseline:

   ```bash
   cd ~/projects/new/balcFlights-LED
   .venv/bin/python tools/no-ai-matrix-test.py
   ```

   Expected: a border box, then `ABCD`, then `Hello world` scrolling. If this fails, the fault is hardware or environment, not application code.

3. Confirm no process owns the bus:

   ```bash
   fuser /dev/spidev0.0
   ```

4. Run the orientation-independent register test:

   ```bash
   .venv/bin/python tests/run_tests.py --matrix-only --phase wiring
   ```

   Expected: fully dark, then every LED on, then dark.

5. Confirm the cascade length, then check every application visual:

   ```bash
   .venv/bin/python tests/run_tests.py --matrix-only --phase blocks
   .venv/bin/python tests/run_tests.py --matrix-only --phase visuals
   ```

6. Run one live flight through the matrix:

   ```bash
   .venv/bin/balc-flights-led --config balc.local.toml once --renderer matrix
   ```

## Recovery

Clear and shut down a stuck display:

```bash
.venv/bin/python tests/run_tests.py --matrix-only --phase off
```

Every phase also blanks the chain in a `finally` block, so an interrupted run
still leaves the matrix dark.