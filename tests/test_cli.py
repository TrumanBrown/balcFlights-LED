import unittest
from pathlib import Path
from unittest.mock import patch

from balc_flights_led import cli
from balc_flights_led.config import load_settings
from balc_flights_led.service import MonitorState


class RecordingMonitor:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def refresh(self) -> MonitorState:
        self.events.append("fetch")
        return MonitorState(kind="empty", pages=(), summary="nothing overhead")


class RecordingRenderer:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def render(self, _item) -> None:
        self.events.append("render")

    def close(self) -> None:
        self.events.append("close")


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings(Path("balc.absent.toml"), environ={})
        self.hub75 = load_settings(Path("balc.absent.toml"), environ={"BFL_PANEL": "hub75"})

    def test_root_is_refused_when_nothing_needs_it(self) -> None:
        with patch.object(cli, "running_as_root", return_value=True):
            for settings, renderer in (
                (self.settings, "matrix"),
                (self.hub75, "console"),
            ):
                with (
                    self.subTest(panel=settings.display.panel, renderer=renderer),
                    self.assertRaisesRegex(RuntimeError, "refusing to run as root"),
                ):
                    cli._refuse_needless_root(settings, renderer)

    def test_root_is_allowed_only_to_open_a_hub75_panel(self) -> None:
        with patch.object(cli, "running_as_root", return_value=True):
            cli._refuse_needless_root(self.hub75, "matrix")
            cli._refuse_needless_root(self.hub75, "both")

    def test_an_unprivileged_user_is_never_refused(self) -> None:
        with patch.object(cli, "running_as_root", return_value=False):
            cli._refuse_needless_root(self.settings, "console")

    def test_once_opens_the_panel_before_fetching(self) -> None:
        events: list[str] = []

        def create(_name, _settings):
            events.append("open")
            return RecordingRenderer(events)

        with patch.object(cli, "_create_renderer", side_effect=create):
            cli._once(RecordingMonitor(events), self.hub75, "matrix")

        # Opening a HUB75 panel is what drops root, so it must precede network I/O.
        self.assertEqual(events[:2], ["open", "fetch"])
        self.assertEqual(events[-1], "close")


if __name__ == "__main__":
    unittest.main()
