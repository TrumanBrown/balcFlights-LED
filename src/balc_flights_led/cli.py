from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Sequence
from pathlib import Path

from .api import FlightApiClient
from .config import RENDERER_CHOICES, Settings, load_settings
from .display import ConsoleRenderer, Max7219Renderer, MultiRenderer, PageRenderer
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
        choices=RENDERER_CHOICES,
        default="console",
        help="Use console by default so API checks never touch SPI unexpectedly",
    )

    run = commands.add_parser("run", help="Continuously refresh and display flights")
    run.add_argument(
        "--renderer",
        choices=RENDERER_CHOICES,
        default=None,
        help="Override display.renderer; 'both' drives the matrix and prints each frame",
    )
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
    if renderer_name != "console":
        renderer = _create_renderer(renderer_name, settings)
        try:
            for item in (*state.intro, *state.pages):
                renderer.render(item)
                if not item.self_timed:
                    time.sleep(settings.display.page_seconds)
        finally:
            renderer.close()
    return 0 if state.kind in {"flight", "stale", "empty"} else 2


def _run(monitor: FlightMonitor, settings: Settings, renderer_name: str) -> int:
    renderer = _create_renderer(renderer_name, settings)
    # Without this, SIGTERM skips the finally block and leaves the matrix lit.
    previous_handler = signal.signal(signal.SIGTERM, _interrupt)
    try:
        run_forever(monitor, renderer, settings)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Stopping flight display")
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        renderer.close()
    return 0


def _interrupt(_signal_number: int, _frame: object) -> None:
    raise KeyboardInterrupt


def _create_renderer(name: str, settings: Settings) -> PageRenderer:
    if name == "console":
        return ConsoleRenderer()
    if name == "matrix":
        return Max7219Renderer(settings.matrix, settings.display)
    if name == "both":
        return MultiRenderer(ConsoleRenderer(), Max7219Renderer(settings.matrix, settings.display))
    raise ValueError(f"unsupported renderer: {name}")
