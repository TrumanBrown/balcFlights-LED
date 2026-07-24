# MAX7219 Hardware Troubleshooting

Last investigated: 2026-07-24 on the target Raspberry Pi 4

## Current Conclusion

The current no-response state is outside the application, font, orientation, Python environment, Luma version, and Linux SPI controller.

Earlier tests produced scrolling and visible pixels, but later commands left a latched garbled pattern and stopped producing any physical change. That transition is characteristic of an intermittent electrical connection or marginal logic levels, not an orientation setting.

Upstream Luma documentation explicitly warns that:

- More than one or two matrices should use a separate regulated 5 V supply with Pi and matrix grounds connected.
- Pi SPI outputs are 3.3 V, outside the MAX7219's guaranteed 5 V input tolerance, and direct drive causes intermittent behavior.
- DIN, CS/LOAD, and CLK should be level-shifted to 5 V.
- In a chain of separate boards, only DOUT-to-DIN is serial; CLK, CS/LOAD, VCC, and ground should be distributed reliably to every board.

Source: [Luma LED matrix notes](https://luma-led-matrix.readthedocs.io/en/latest/notes.html)

## What Was Verified

- Pi model: Raspberry Pi 4 Model B Rev 1.5.
- Kernel: `6.12.93+rpt-rpi-v8`.
- SPI controller and `spidev` modules load without errors.
- `/dev/spidev0.0` maps to SPI0 CE0 and `/dev/spidev0.1` maps to CE1.
- BCM10 is SPI0 MOSI, BCM11 is SPI0 SCLK, and BCM8 is kernel-owned CE0, idle high.
- No background process holds or rewrites either SPI device.
- The Pi reports no undervoltage or throttling history.
- The legacy and current Luma versions have equivalent MAX7219 and SPI implementations.
- The unchanged legacy script and the new driver both complete without software errors.
- CE0 and CE1 were each tested at 500 kHz with direct MAX7219 display-test, clear, and shutdown commands; neither produced a visible change.
- A separate slow software-SPI implementation toggled BCM10/11/8 directly and sent ten full clear/shutdown cycles. Hardware SPI pin modes were restored afterward.
- A reboot did not restore communication.

There is no MAX7219 readback connection, so a successful Linux write only proves bytes reached the Pi's GPIO peripheral. It cannot prove continuity, voltage, or signal quality at the matrix input header.

## Required Wiring Check

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

## Test Order After Wiring

1. Power-cycle the matrix supply, not merely Linux. The MAX7219 has no reset pin.
2. Confirm no process owns the bus:

   ```bash
   fuser /dev/spidev0.0
   ```

3. Run the orientation-independent register test:

   ```bash
   cd ~/projects/new/balcFlights-LED
   .venv/bin/python tools/matrix_bus_test.py --speed-hz 500000
   ```

   Expected: dark for 3 seconds, every LED on for 5 seconds, then dark.

4. Only after that sequence works, calibrate text orientation:

   ```bash
   .venv/bin/python tools/matrix_orientation_test.py --speed-hz 500000
   ```

5. Run one live flight through the matrix:

   ```bash
   .venv/bin/balc-flights-led --config balc.local.toml once --renderer matrix
   ```

## Recovery Utilities

Normal clear and shutdown:

```bash
.venv/bin/python tools/clear_matrix.py --speed-hz 500000 --retries 10
```

`tools/matrix_software_spi_recovery.py` is a last-resort diagnostic that temporarily takes over BCM10/11/8 with `RPi.GPIO`. It is not part of normal operation. After using it, restore BCM8 as idle-high output and BCM10/11 as SPI0 ALT0 before returning to `spidev`.

Install its optional dependency into the project environment before use:

```bash
.venv/bin/python -m pip install -e '.[recovery]'
```