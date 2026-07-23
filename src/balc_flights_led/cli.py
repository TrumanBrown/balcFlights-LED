from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from .api import FlightApiClient
from .config import Settings, load_settings
from .display import ConsoleRenderer, Max7219Renderer, PageRenderer
from .presentation import DisplayPage
from .service import FlightMonitor, run_forever


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="balc-flights-led",
        description="Display the nearest Seattle Balc flight on a MAX7219 LED matrix.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("balc.local.toml"),
        help="TOML configuration path (default: balc.local.toml)",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    once = commands.add_parser("once", help="Fetch and display one nearest-flight result")
    once.add_argument(
        "--renderer",
        choices=("console", "matrix"),
        default="console",
        help="Use console by default so API checks never touch SPI unexpectedly",
    )

    run = commands.add_parser("run", help="Continuously refresh and display flights")
    run.add_argument(
        "--renderer",
        choices=("console", "matrix"),
        default=None,
        help="Override display.renderer from the TOML configuration",
    )

    matrix_test = commands.add_parser(
        "matrix-test",
        help="Show short text and cardinal arrows without calling the flight API",
    )
    matrix_test.add_argument("--seconds", type=float, default=1.5, help="Seconds per test page")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, arguments.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        settings = load_settings(arguments.config)
        if arguments.command == "matrix-test":
            return _matrix_test(settings, arguments.seconds)

        client = FlightApiClient(
            settings.api.endpoint,
            timeout_seconds=settings.api.timeout_seconds,
        )
        monitor = FlightMonitor(settings, client)

        if arguments.command == "once":
            return _once(monitor, settings, arguments.renderer)
        if arguments.command == "run":
            renderer_name = arguments.renderer or settings.display.renderer
            return _run(monitor, settings, renderer_name)
    except (OSError, RuntimeError, ValueError) as error:
        logging.getLogger(__name__).error("%s", error)
        return 2

    parser.error(f"unsupported command: {arguments.command}")
    return 2


def _once(monitor: FlightMonitor, settings: Settings, renderer_name: str) -> int:
    state = monitor.refresh()
    print(state.summary, flush=True)
    if renderer_name == "matrix":
        renderer = _create_renderer(renderer_name, settings)
        try:
            for page in state.pages:
                renderer.render(page)
                time.sleep(settings.display.page_seconds)
        finally:
            renderer.close()
    return 0 if state.kind in {"flight", "stale", "empty"} else 2


def _run(monitor: FlightMonitor, settings: Settings, renderer_name: str) -> int:
    renderer = _create_renderer(renderer_name, settings)
    try:
        run_forever(monitor, renderer, settings)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Stopping flight display")
    finally:
        renderer.close()
    return 0


def _matrix_test(settings: Settings, seconds_per_page: float) -> int:
    if seconds_per_page <= 0:
        raise ValueError("matrix-test --seconds must be greater than 0")

    renderer = Max7219Renderer(settings.matrix)
    pages = (
        DisplayPage("N", bearing_degrees=0),
        DisplayPage("E", bearing_degrees=90),
        DisplayPage("S", bearing_degrees=180),
        DisplayPage("W", bearing_degrees=270),
        DisplayPage("1234"),
        DisplayPage("STALE", stale=True),
    )
    try:
        for page in pages:
            renderer.render(page)
            time.sleep(seconds_per_page)
    finally:
        renderer.close()
    return 0


def _create_renderer(name: str, settings: Settings) -> PageRenderer:
    if name == "console":
        return ConsoleRenderer()
    if name == "matrix":
        return Max7219Renderer(settings.matrix)
    raise ValueError(f"unsupported renderer: {name}")
