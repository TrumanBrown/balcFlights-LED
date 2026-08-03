"""Single entry point for every check in this project.

# Software only. Never opens SPI, safe anywhere.
.venv/bin/python tests/run_tests.py

# Software checks, then drive the real MAX7219 chain.
.venv/bin/python tests/run_tests.py --matrix

# Isolate one hardware phase, or blank a stuck display.
.venv/bin/python tests/run_tests.py --matrix --phase wiring
.venv/bin/python tests/run_tests.py --matrix --phase off
"""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Any

TESTS_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIRECTORY.parent

# MAX7219 register addresses (datasheet table 2).
REG_SHUTDOWN = 0x0C
REG_DISPLAY_TEST = 0x0F
ROW_REGISTERS = range(1, 9)

PHASES = ("wiring", "blocks", "visuals", "off")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the balcFlights-LED test suite, and optionally the LED matrix.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Hardware phases:\n"
            "  wiring   raw display-test register toggle; proves VCC/GND/DIN/CLK/CS\n"
            "  blocks   lights each 8x8 block in turn; proves the cascade length\n"
            "  visuals  every frame the application can draw, including animations\n"
            "  off      clears every row and enters shutdown\n"
        ),
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Also drive the physical matrix over SPI",
    )
    parser.add_argument(
        "--matrix-only",
        action="store_true",
        help="Skip the unit tests and run hardware checks only",
    )
    parser.add_argument(
        "--phase",
        choices=PHASES,
        help="Run a single hardware phase instead of all of them",
    )
    parser.add_argument("--seconds", type=float, default=1.5, help="Dwell per visual step")
    parser.add_argument("-q", "--quiet", action="store_true", help="Less unit test output")
    return parser


def run_unit_tests(*, verbosity: int) -> bool:
    print("=" * 70, flush=True)
    print("unit tests", flush=True)
    print("=" * 70, flush=True)
    suite = unittest.TestLoader().discover(
        str(TESTS_DIRECTORY),
        top_level_dir=str(TESTS_DIRECTORY),
    )
    return unittest.TextTestRunner(verbosity=verbosity).run(suite).wasSuccessful()


def run_matrix_checks(phases: Sequence[str], seconds: float) -> bool:
    from balc_flights_led.config import load_settings
    from balc_flights_led.display import Max7219Renderer, force_max7219_off

    print("=" * 70, flush=True)
    print(f"matrix: {', '.join(phases)}", flush=True)
    print("=" * 70, flush=True)

    settings = load_settings(PROJECT_ROOT / "balc.local.toml")
    matrix = settings.matrix
    print(
        f"MAX7219 {matrix.cascaded * 8}x8 on SPI{matrix.spi_port}.{matrix.spi_device} "
        f"at {matrix.spi_speed_hz} Hz (block_orientation={matrix.block_orientation}, "
        f"rotate={matrix.rotate}, reverse_order={matrix.reverse_order}, "
        f"contrast={matrix.contrast})",
        flush=True,
    )

    renderer = Max7219Renderer(matrix, settings.display)
    device = renderer.device
    try:
        for phase in phases:
            print(f"[{phase}]", flush=True)
            if phase == "wiring":
                _phase_wiring(device, seconds)
            elif phase == "blocks":
                _phase_blocks(device, seconds)
            elif phase == "visuals":
                _phase_visuals(renderer, seconds)
            elif phase == "off":
                force_max7219_off(device, device.cascaded)
                print("  cleared and shut down", flush=True)
    except KeyboardInterrupt:
        print("\ninterrupted", flush=True)
    finally:
        renderer.close()

    print("matrix checks are observational; confirm the expectations above by eye", flush=True)
    return True


def _broadcast(device: Any, register: int, value: int) -> None:
    """Write one register on every chip in the chain."""
    device.data([register, value] * device.cascaded)


def _wake(device: Any) -> None:
    _broadcast(device, REG_DISPLAY_TEST, 0)
    _broadcast(device, REG_SHUTDOWN, 1)


def _phase_wiring(device: Any, seconds: float) -> None:
    """Toggle the display-test register, bypassing fonts, orientation, and the framebuffer."""
    from balc_flights_led.display import force_max7219_off

    print("  expect: fully dark", flush=True)
    force_max7219_off(device, device.cascaded)
    time.sleep(seconds)

    print("  expect: every LED lit on all blocks", flush=True)
    _wake(device)
    _broadcast(device, REG_DISPLAY_TEST, 1)
    time.sleep(seconds)
    _broadcast(device, REG_DISPLAY_TEST, 0)

    print("  nothing lit here means power or signal wiring, not orientation", flush=True)


def _phase_blocks(device: Any, seconds: float) -> None:
    """Light one 8x8 block at a time using raw row registers."""
    _wake(device)
    for position in range(device.cascaded):
        for row in ROW_REGISTERS:
            payload: list[int] = []
            for chip in range(device.cascaded):
                payload.extend([row, 0xFF if chip == position else 0x00])
            device.data(payload)
        print(f"  block {position + 1} of {device.cascaded} lit", flush=True)
        time.sleep(seconds)
    print("  count the blocks to confirm matrix.cascaded", flush=True)


def _phase_visuals(renderer: Any, seconds: float) -> None:
    from balc_flights_led.presentation import (
        ArrivalAnimation,
        DisplayPage,
        IdleAnimation,
        MarqueePage,
    )

    items = (
        ArrivalAnimation("TEST", bearing_degrees=45),
        DisplayPage("ASA123", bearing_degrees=0, proximity=0.9),
        DisplayPage("ASA123", bearing_degrees=90, proximity=0.9),
        DisplayPage("ASA123", bearing_degrees=180, proximity=0.9),
        DisplayPage("ASA123", bearing_degrees=270, proximity=0.9),
        DisplayPage("ASA123", trend=1, proximity=0.6),
        DisplayPage("ASA123", trend=-1, proximity=0.3),
        DisplayPage("ASA123", trend=0, proximity=0.1),
        DisplayPage("QXE2372", bearing_degrees=0, proximity=1.0),
        DisplayPage("QXE2372", trend=1, proximity=1.0),
        DisplayPage("ASA123", bearing_degrees=315, proximity=0.95, overhead=True),
        DisplayPage("ASA123", bearing_degrees=90, proximity=0.5, stale=True),
        MarqueePage("ASA123 B739 2.4NM SE 5500FT CLB 266KT"),
        IdleAnimation(seconds=seconds * 2),
    )
    for item in items:
        renderer.render(item)
        if not item.self_timed:
            time.sleep(seconds)
    print("  the callsign stays on screen for every frame", flush=True)
    print("  right-hand cell cycles: bearing arrow, then climb/level/descend chevrons", flush=True)
    print("  bottom row is the proximity bar: longer means closer", flush=True)
    print("  QXE2372 is 7 characters, so its indicator is squeezed into 4 columns", flush=True)
    print("  the overhead frame inverts the indicator cell; STALE lights the top-right pixel")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.seconds <= 0:
        raise SystemExit("--seconds must be greater than zero")
    if arguments.phase and not (arguments.matrix or arguments.matrix_only):
        raise SystemExit("--phase requires --matrix or --matrix-only")

    successful = True
    if not arguments.matrix_only:
        successful = run_unit_tests(verbosity=1 if arguments.quiet else 2)

    if arguments.matrix or arguments.matrix_only:
        phases = [arguments.phase] if arguments.phase else list(PHASES)
        successful = run_matrix_checks(phases, arguments.seconds) and successful

    print("PASSED" if successful else "FAILED", flush=True)
    return 0 if successful else 1


if __name__ == "__main__":
    sys.exit(main())
