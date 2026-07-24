from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

DISPLAY_TEST = 0x0F


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test MAX7219 communication with an all-on, then all-off sequence."
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--cascaded", type=int, default=4)
    parser.add_argument("--speed-hz", type=int, default=500_000)
    parser.add_argument("--ready-seconds", type=float, default=3.0)
    parser.add_argument("--on-seconds", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.cascaded <= 0:
        raise SystemExit("--cascaded must be greater than zero")
    if arguments.speed_hz <= 0:
        raise SystemExit("--speed-hz must be greater than zero")
    if arguments.ready_seconds < 0 or arguments.on_seconds <= 0:
        raise SystemExit("delays must be non-negative and --on-seconds must be positive")

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
        matrix.clear()
        print(f"READY: matrix dark for {arguments.ready_seconds:g} seconds", flush=True)
        time.sleep(arguments.ready_seconds)

        print(f"ON: every LED for {arguments.on_seconds:g} seconds", flush=True)
        matrix.data([DISPLAY_TEST, 1] * arguments.cascaded)
        time.sleep(arguments.on_seconds)

        print("OFF: clearing and entering shutdown", flush=True)
        matrix.data([DISPLAY_TEST, 0] * arguments.cascaded)
        matrix.clear()
        matrix.hide()
    finally:
        matrix.cleanup()

    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
