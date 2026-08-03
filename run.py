"""Start the live overhead-flight display. This is the file to run.

    .venv/bin/python run.py                     # LED matrix, per balc.local.toml
    .venv/bin/python run.py --renderer console  # terminal only, never opens SPI

Press Ctrl+C to stop. The matrix is blanked on exit, including on SIGTERM.
"""

from __future__ import annotations

import sys
from pathlib import Path

from balc_flights_led.cli import main as cli_main

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "balc.local.toml"


def main() -> int:
    if not CONFIG_PATH.exists():
        print(
            f"missing {CONFIG_PATH.name}. Run: cp balc.example.toml balc.local.toml",
            file=sys.stderr,
        )
        return 2

    print(f"config    {CONFIG_PATH}")
    print("headline  bearing arrow + callsign of the nearest aircraft")
    print("scroll    full detail line once per refresh")
    print("sprite    plane flies past when a different aircraft becomes nearest")
    print("dashes    bottom row lit while that aircraft is inside the overhead radius")
    print("idle      drifting dots when nothing qualifies")
    print("Ctrl+C to stop", flush=True)

    return cli_main(["--config", str(CONFIG_PATH), "run", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
