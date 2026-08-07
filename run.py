"""Start the live overhead-flight display. This is the file to run.

    .venv/bin/python run.py                     # LED matrix, per balc.local.toml
    .venv/bin/python run.py --renderer console  # terminal only, never opens SPI
    .venv/bin/python run.py --panel hub75       # HUB75 RGB panel instead of the MAX7219

Press Ctrl+C to stop. The matrix is blanked on exit, including on SIGTERM.
"""

from __future__ import annotations

import sys
from pathlib import Path

from balc_flights_led.cli import main as cli_main
from balc_flights_led.config import load_settings

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "balc.local.toml"

LAYOUTS = {
    "max7219": (
        "headline  bearing arrow + callsign of the nearest aircraft",
        "scroll    full detail line once per refresh",
        "sprite    plane flies past when a different aircraft becomes nearest",
        "dashes    bottom row lit while that aircraft is inside the overhead radius",
        "idle      drifting dots when nothing qualifies",
    ),
    "hub75": (
        "headline  callsign across the top, scaled to the panel",
        "arrow     large bearing arrow filling the middle, amber while overhead",
        "bar       full-width proximity bar along the bottom, green to red as it closes",
        "scroll    full detail line once per refresh",
        "sprite    plane flies past when a different aircraft becomes nearest",
        "idle      drifting dots when nothing qualifies",
    ),
}


def main() -> int:
    if not CONFIG_PATH.exists():
        print(
            f"missing {CONFIG_PATH.name}. Run: cp balc.example.toml balc.local.toml",
            file=sys.stderr,
        )
        return 2

    arguments = sys.argv[1:]
    panel = _selected_panel(arguments)
    print(f"config    {CONFIG_PATH}")
    print(f"panel     {panel}")
    for line in LAYOUTS[panel]:
        print(line)
    print("Ctrl+C to stop", flush=True)

    return cli_main(["--config", str(CONFIG_PATH), "run", *arguments])


def _selected_panel(arguments: list[str]) -> str:
    if "--panel" in arguments:
        candidate = arguments[arguments.index("--panel") + 1 :]
        if candidate and candidate[0] in LAYOUTS:
            return candidate[0]
    try:
        return load_settings(CONFIG_PATH).display.panel
    except (OSError, ValueError):
        return "max7219"


if __name__ == "__main__":
    sys.exit(main())
