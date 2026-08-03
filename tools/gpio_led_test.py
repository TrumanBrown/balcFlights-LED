"""Blink an LED on a single GPIO pin to confirm the Pi's GPIO hardware still works.

Use this after any suspected back-powering incident, on a pin that was NOT part
of the suspect wiring, to prove the SoC survived.

Wiring (defaults to BCM 26 = physical pin 37):

    GPIO 26 (pin 37) ---[ 220-330 ohm ]--- LED anode (long leg)
                                           LED cathode (short leg) --- GND (pin 39)

Pin 39 is the ground pin directly beside pin 37, so the whole test spans two
adjacent header positions. Polarity matters: the LED only lights one way round.
The resistor is mandatory. A bare LED across 3.3 V draws far more than the
~16 mA a single GPIO pin can source and will damage the pin.

At 220 ohm a red LED draws about 6 mA, comfortably inside spec.

    .venv/bin/python tools/gpio_led_test.py
    .venv/bin/python tools/gpio_led_test.py --pin 21 --blinks 10
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

# BCM numbering -> physical header pin, for the pins that are safe general IO.
# fmt: off
PHYSICAL_PINS = {
    4: 7, 5: 29, 6: 31, 8: 24, 9: 21, 10: 19, 11: 23, 12: 32, 13: 33,
    16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
    24: 18, 25: 22, 26: 37, 27: 13,
}
# fmt: on

# SPI0 pins used by the MAX7219 wiring; blinking these fights the display driver.
SPI0_PINS = {8, 9, 10, 11}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Blink an LED on one GPIO pin to verify the Pi's GPIO still works."
    )
    parser.add_argument("--pin", type=int, default=26, help="BCM pin number (default: 26)")
    parser.add_argument("--blinks", type=int, default=5, help="Blink count (default: 5)")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds per on/off state")
    parser.add_argument("--hold", type=float, default=3.0, help="Seconds to hold steady on at end")
    parser.add_argument(
        "--allow-spi-pins",
        action="store_true",
        help="Permit BCM 8/9/10/11. Only with the matrix physically unplugged.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not 0 <= arguments.pin <= 27:
        raise SystemExit("--pin must be a BCM number between 0 and 27")
    if arguments.pin in SPI0_PINS and not arguments.allow_spi_pins:
        raise SystemExit(
            f"BCM {arguments.pin} belongs to SPI0 and is used by the matrix wiring. "
            "Pick an unrelated pin such as 26, or pass --allow-spi-pins with the "
            "matrix physically unplugged."
        )
    if arguments.blinks <= 0:
        raise SystemExit("--blinks must be greater than zero")
    if arguments.interval <= 0:
        raise SystemExit("--interval must be greater than zero")
    if arguments.hold < 0:
        raise SystemExit("--hold cannot be negative")

    try:
        import RPi.GPIO as GPIO
    except ImportError as error:
        raise SystemExit(
            "RPi.GPIO is not installed. Run: .venv/bin/pip install -e '.[recovery]'"
        ) from error

    physical = PHYSICAL_PINS.get(arguments.pin)
    location = f"BCM {arguments.pin}" + (f" (physical pin {physical})" if physical else "")
    print(f"Blinking an LED on {location}", flush=True)
    print(f"  anode via 220-330 ohm resistor to {location}, cathode to any GND pin", flush=True)

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(arguments.pin, GPIO.OUT, initial=GPIO.LOW)
    try:
        for index in range(1, arguments.blinks + 1):
            GPIO.output(arguments.pin, GPIO.HIGH)
            print(f"  blink {index}/{arguments.blinks}: on", flush=True)
            time.sleep(arguments.interval)
            GPIO.output(arguments.pin, GPIO.LOW)
            time.sleep(arguments.interval)

        if arguments.hold:
            print(f"  steady on for {arguments.hold:g}s", flush=True)
            GPIO.output(arguments.pin, GPIO.HIGH)
            time.sleep(arguments.hold)
    except KeyboardInterrupt:
        print("\ninterrupted", flush=True)
    finally:
        GPIO.output(arguments.pin, GPIO.LOW)
        GPIO.cleanup(arguments.pin)

    print("DONE", flush=True)
    print("If the LED blinked, this GPIO pin and the SoC are fine.", flush=True)
    print("If it never lit, try reversing the LED legs before suspecting the Pi.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
