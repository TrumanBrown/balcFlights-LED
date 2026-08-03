import unittest
from unittest.mock import patch

from luma.core.device import dummy

from balc_flights_led.config import DisplaySettings, MatrixSettings
from balc_flights_led.display import (
    DISPLAY_TEST,
    PLANE_SPRITE,
    SHUTDOWN,
    SHUTDOWN_RETRIES,
    SPRITE_WIDTH,
    ConsoleRenderer,
    Max7219Renderer,
    MultiRenderer,
    force_max7219_off,
)
from balc_flights_led.presentation import ArrivalAnimation, DisplayPage, IdleAnimation, MarqueePage


class FakeMatrix:
    def __init__(self) -> None:
        self.writes: list[list[int]] = []

    def data(self, values: list[int]) -> None:
        self.writes.append(values)


class RecordingRenderer:
    def __init__(self) -> None:
        self.rendered: list[object] = []
        self.closed = False

    def render(self, item: object) -> None:
        self.rendered.append(item)

    def close(self) -> None:
        self.closed = True


class DisplayTests(unittest.TestCase):
    @patch("balc_flights_led.display.time.sleep")
    def test_force_off_repeats_display_test_clear_and_shutdown(self, sleep) -> None:
        matrix = FakeMatrix()

        force_max7219_off(matrix, cascaded=2)

        cycle = [[DISPLAY_TEST, 0] * 2]
        cycle.extend([[row, 0] * 2 for row in range(1, 9)])
        cycle.append([SHUTDOWN, 0] * 2)
        self.assertEqual(matrix.writes, cycle * SHUTDOWN_RETRIES)
        self.assertEqual(sleep.call_count, SHUTDOWN_RETRIES)

    def test_plane_sprite_fits_an_eight_row_matrix(self) -> None:
        self.assertLessEqual(len(PLANE_SPRITE), 8)
        self.assertTrue(all(len(row) == SPRITE_WIDTH for row in PLANE_SPRITE))
        self.assertTrue(set("".join(PLANE_SPRITE)) <= {"#", "."})

    @patch("builtins.print")
    def test_console_renderer_handles_every_item_type(self, printer) -> None:
        renderer = ConsoleRenderer()

        renderer.render(DisplayPage("ASA123", bearing_degrees=90, overhead=True, stale=True))
        renderer.render(MarqueePage("ASA123 2.4NM"))
        renderer.render(ArrivalAnimation("ASA123"))
        renderer.render(IdleAnimation(seconds=4.0))
        renderer.close()

        rendered = [call.args[0] for call in printer.call_args_list]
        self.assertEqual(
            rendered,
            [
                "ASA123 | bearing=90 | OVERHEAD | STALE",
                "[scroll] ASA123 2.4NM",
                "[arrival] ASA123",
                "[idle 4s]",
            ],
        )

    def test_multi_renderer_fans_out_and_closes_every_target(self) -> None:
        first, second = RecordingRenderer(), RecordingRenderer()
        page = DisplayPage("ASA123")

        renderer = MultiRenderer(first, second)
        renderer.render(page)
        renderer.close()

        self.assertEqual(first.rendered, [page])
        self.assertEqual(second.rendered, [page])
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)


class MatrixLayoutTests(unittest.TestCase):
    """Render to an offscreen device so the 32x8 layout is checked, not assumed."""

    def render(self, page: DisplayPage, font: str = "atari"):
        device = dummy(width=32, height=8, mode="1")
        renderer = Max7219Renderer(MatrixSettings(), DisplaySettings(font=font), device=device)
        renderer.render(page)
        return device.image.load()

    def lit_columns(self, pixels, row: int) -> list[int]:
        return [column for column in range(32) if pixels[column, row]]

    def lit_in_region(self, pixels, *, first_column: int) -> int:
        """Count lit pixels on the glyph rows, right of the given column."""
        return sum(
            1 for row in range(6) for column in range(first_column, 32) if pixels[column, row]
        )

    def test_callsign_and_proximity_bar_share_the_frame(self) -> None:
        pixels = self.render(DisplayPage("ASA123", bearing_degrees=0, proximity=0.5))

        self.assertEqual(self.lit_columns(pixels, 7), list(range(16)))
        self.assertTrue(self.lit_columns(pixels, 1))
        # Row 6 is the gap that keeps the bar clear of the glyphs.
        self.assertEqual(self.lit_columns(pixels, 6), [])

    def test_seven_character_callsign_still_gets_an_indicator(self) -> None:
        pixels = self.render(DisplayPage("QXE2372", bearing_degrees=0, proximity=1.0))

        # QXE2372 is 28px, leaving exactly the 4 columns an indicator needs.
        self.assertGreater(self.lit_in_region(pixels, first_column=28), 0)

    def test_indicator_is_skipped_when_the_callsign_fills_the_matrix(self) -> None:
        pixels = self.render(DisplayPage("ABCDEFGH", bearing_degrees=0, proximity=1.0))

        self.assertEqual(self.lit_columns(pixels, 7), list(range(32)))

    def test_bearing_arrow_and_climb_chevrons_differ(self) -> None:
        north = self.render(DisplayPage("ASA123", bearing_degrees=0, proximity=0.5))
        climbing = self.render(DisplayPage("ASA123", trend=1, proximity=0.5))

        north_cell = [self.lit_columns(north, row) for row in range(6)]
        climb_cell = [self.lit_columns(climbing, row) for row in range(6)]
        self.assertNotEqual(north_cell, climb_cell)

    def test_overhead_inverts_the_indicator_cell(self) -> None:
        plain = self.render(DisplayPage("ASA123", bearing_degrees=90, proximity=0.5))
        overhead = self.render(
            DisplayPage("ASA123", bearing_degrees=90, proximity=0.5, overhead=True)
        )

        self.assertGreater(
            sum(len(self.lit_columns(overhead, row)) for row in range(6)),
            sum(len(self.lit_columns(plain, row)) for row in range(6)),
        )


if __name__ == "__main__":
    unittest.main()
