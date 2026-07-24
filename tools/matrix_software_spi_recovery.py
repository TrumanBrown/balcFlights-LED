from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

DECODE_MODE = 0x09
INTENSITY = 0x0A
SCAN_LIMIT = 0x0B
SHUTDOWN = 0x0C
DISPLAY_TEST = 0x0F


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear a MAX7219 chain with slow software SPI on Raspberry Pi GPIO."
    )
    parser.add_argument("--clock", type=int, default=11, help="BCM clock GPIO")
    parser.add_argument("--data", type=int, default=10, help="BCM MOSI GPIO")
    parser.add_argument("--load", type=int, default=8, help="BCM LOAD/CS GPIO")
    parser.add_argument("--cascaded", type=int, default=4)
    parser.add_argument("--half-period-us", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.cascaded <= 0 or arguments.retries <= 0:
        raise SystemExit("--cascaded and --retries must be greater than zero")
    if arguments.half_period_us <= 0:
        raise SystemExit("--half-period-us must be greater than zero")

    import RPi.GPIO as GPIO

    delay_seconds = arguments.half_period_us / 1_000_000
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(arguments.clock, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(arguments.data, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(arguments.load, GPIO.OUT, initial=GPIO.HIGH)

    def send(register: int, value: int) -> None:
        GPIO.output(arguments.load, GPIO.LOW)
        for byte in [register, value] * arguments.cascaded:
            for bit in range(7, -1, -1):
                GPIO.output(arguments.data, bool(byte & (1 << bit)))
                time.sleep(delay_seconds)
                GPIO.output(arguments.clock, GPIO.HIGH)
                time.sleep(delay_seconds)
                GPIO.output(arguments.clock, GPIO.LOW)
        time.sleep(delay_seconds)
        GPIO.output(arguments.load, GPIO.HIGH)
        time.sleep(delay_seconds)

    try:
        for _ in range(arguments.retries):
            send(DISPLAY_TEST, 0)
            send(DECODE_MODE, 0)
            send(SCAN_LIMIT, 7)
            send(INTENSITY, 0)
            for row in range(1, 9):
                send(row, 0)
            send(SHUTDOWN, 0)
    finally:
        GPIO.output(arguments.load, GPIO.HIGH)
        GPIO.output(arguments.clock, GPIO.LOW)
        GPIO.output(arguments.data, GPIO.LOW)
        GPIO.cleanup((arguments.clock, arguments.data, arguments.load))

    print(
        f"Sent {arguments.retries} slow clear/shutdown cycles to "
        f"{arguments.cascaded} MAX7219 modules on BCM "
        f"DIN={arguments.data}, CLK={arguments.clock}, LOAD={arguments.load}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
