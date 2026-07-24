from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

SPI_SPEEDS_HZ = (500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clear and shut down a MAX7219 matrix chain.")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--cascaded", type=int, default=4)
    parser.add_argument("--speed-hz", type=int, choices=SPI_SPEEDS_HZ, default=500_000)
    parser.add_argument("--retries", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.port < 0 or arguments.device < 0:
        raise SystemExit("--port and --device cannot be negative")
    if arguments.cascaded <= 0:
        raise SystemExit("--cascaded must be greater than zero")
    if arguments.retries <= 0:
        raise SystemExit("--retries must be greater than zero")

    from luma.core.interface.serial import noop, spi
    from luma.led_matrix.device import max7219

    serial = spi(
        port=arguments.port,
        device=arguments.device,
        gpio=noop(),
        bus_speed_hz=arguments.speed_hz,
    )
    matrix = max7219(serial, cascaded=arguments.cascaded)
    try:
        for _ in range(arguments.retries):
            matrix.clear()
            matrix.hide()
            time.sleep(0.02)
    finally:
        matrix.cleanup()

    print(
        f"Cleared and shut down {arguments.cascaded} MAX7219 modules "
        f"on SPI{arguments.port}.{arguments.device} at {arguments.speed_hz} Hz."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
