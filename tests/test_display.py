import unittest
from unittest.mock import patch

from luma.core.device import dummy

from balc_flights_led.config import DisplaySettings, MatrixSettings
from balc_flights_led.display import (
    ARROW_HEIGHT,
    ARROW_SPRITES,
    ARROW_WIDTH,
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

    def lit_columns(self, pixels, row: int, *, until: int = 32) -> list[int]:
        return [column for column in range(until) if pixels[column, row]]

    def arrow_block(self, pixels) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(1 if pixels[column, row] else 0 for column in range(32 - ARROW_WIDTH, 32))
            for row in range(ARROW_HEIGHT)
        )

    def expected_block(self, octant: int) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(1 if cell == "#" else 0 for cell in row) for row in ARROW_SPRITES[octant]
        )

    def test_callsign_and_proximity_bar_share_the_frame(self) -> None:
        pixels = self.render(DisplayPage("ASA123", bearing_degrees=0, proximity=0.5))

        # The bar spans only the 24px callsign area, so it cannot reach the arrow.
        self.assertEqual(self.lit_columns(pixels, 7, until=24), list(range(12)))
        self.assertTrue(self.lit_columns(pixels, 1, until=24))
        # Row 6 is the gap that keeps the bar clear of the glyphs.
        self.assertEqual(self.lit_columns(pixels, 6, until=24), [])

    def test_arrow_block_matches_the_sprite_for_every_octant(self) -> None:
        for octant, bearing in enumerate(range(0, 360, 45)):
            with self.subTest(bearing=bearing):
                pixels = self.render(DisplayPage("ASA123", bearing_degrees=bearing))
                self.assertEqual(self.arrow_block(pixels), self.expected_block(octant))

    def test_bearing_snaps_to_the_nearest_octant(self) -> None:
        for bearing, octant in ((22.0, 0), (23.0, 1), (350.0, 0), (181.0, 4)):
            with self.subTest(bearing=bearing):
                pixels = self.render(DisplayPage("ASA123", bearing_degrees=bearing))
                self.assertEqual(self.arrow_block(pixels), self.expected_block(octant))

    def test_long_callsign_is_clipped_instead_of_overwriting_the_arrow(self) -> None:
        pixels = self.render(DisplayPage("QXE2372", bearing_degrees=0, proximity=1.0))

        self.assertEqual(self.arrow_block(pixels), self.expected_block(0))

    def test_status_page_without_a_bearing_uses_the_whole_width(self) -> None:
        pixels = self.render(DisplayPage("OFFLINE"))

        lit = [column for row in range(8) for column in self.lit_columns(pixels, row)]
        self.assertTrue(lit)
        self.assertGreaterEqual(max(lit), 24)

    def test_overhead_inverts_the_arrow_block(self) -> None:
        plain = self.render(DisplayPage("ASA123", bearing_degrees=90, proximity=0.5))
        overhead = self.render(
            DisplayPage("ASA123", bearing_degrees=90, proximity=0.5, overhead=True)
        )

        self.assertGreater(
            sum(sum(row) for row in self.arrow_block(overhead)),
            sum(sum(row) for row in self.arrow_block(plain)),
        )


if __name__ == "__main__":
    unittest.main()
