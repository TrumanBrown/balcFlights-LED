import math
import sys
import types
import unittest
from typing import Any
from unittest.mock import patch

from luma.core.device import dummy

from balc_flights_led.config import DisplaySettings, Hub75Settings, MatrixSettings
from balc_flights_led.display import (
    ARROW_HEIGHT,
    ARROW_SPRITES,
    ARROW_WIDTH,
    DISPLAY_TEST,
    MINIMUM_VECTOR_ARROW,
    PLANE_SPRITE,
    RADAR_AFTERGLOW_FLOOR,
    RADAR_TARGET_COLOR,
    SHUTDOWN,
    SHUTDOWN_RETRIES,
    SPRITE_WIDTH,
    TREND_COLORS,
    ConsoleRenderer,
    Hub75Renderer,
    Max7219Renderer,
    MultiRenderer,
    _dim,
    force_max7219_off,
    open_hub75,
)
from balc_flights_led.presentation import (
    ArrivalAnimation,
    DisplayPage,
    IdleAnimation,
    MarqueePage,
    RadarPage,
    RadarTrack,
)

# Every settable property of rgbmatrix.RGBMatrixOptions, taken from the binding's
# core.pyx. __slots__ makes a typo in open_hub75 an immediate AttributeError.
RGB_MATRIX_OPTION_NAMES = (
    "hardware_mapping",
    "rows",
    "cols",
    "chain_length",
    "parallel",
    "pwm_bits",
    "pwm_lsb_nanoseconds",
    "brightness",
    "scan_mode",
    "multiplexing",
    "row_address_type",
    "disable_hardware_pulsing",
    "show_refresh_rate",
    "inverse_colors",
    "led_rgb_sequence",
    "pixel_mapper_config",
    "panel_type",
    "pwm_dither_bits",
    "limit_refresh_rate_hz",
    "gpio_slowdown",
    "rp1_pio",
    "daemon",
    "drop_privileges",
    "drop_priv_user",
    "drop_priv_group",
)


class FakeOptions:
    __slots__ = RGB_MATRIX_OPTION_NAMES


class FakeCanvas:
    def __init__(self, panel: "FakePanel") -> None:
        self._panel = panel
        self.image = None

    def SetImage(self, image) -> None:
        self.image = image.copy()


class FakePanel:
    """Stands in for rgbmatrix.RGBMatrix so the HUB75 layout is testable offscreen."""

    def __init__(self, width: int = 64, height: int = 64) -> None:
        self.width = width
        self.height = height
        self.frames: list[object] = []
        self.cleared = 0

    def CreateFrameCanvas(self) -> FakeCanvas:
        return FakeCanvas(self)

    def SwapOnVSync(self, canvas: FakeCanvas) -> FakeCanvas:
        self.frames.append(canvas.image)
        return FakeCanvas(self)

    def Clear(self) -> None:
        self.cleared += 1


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

    @patch("builtins.print")
    def test_console_renderer_summarises_a_radar_page(self, printer) -> None:
        renderer = ConsoleRenderer()

        renderer.render(
            RadarPage(
                range_nautical_miles=20.0,
                tracks=(
                    RadarTrack("ASA123", 2.4, 135.0, trend=1, nearest=True),
                    RadarTrack("DAL88", 9.1, 20.0),
                ),
                label="ASA123",
                distance_text="2.4NM",
                compass="SE",
                overhead=True,
            )
        )

        self.assertEqual(
            printer.call_args_list[0].args[0],
            "[radar] ASA123 | tracks=2 | 2.4NM SE | OVERHEAD",
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

    def test_overhead_no_longer_inverts_the_arrow_block(self) -> None:
        plain = self.render(DisplayPage("ASA123", bearing_degrees=90, proximity=0.5))
        overhead = self.render(
            DisplayPage("ASA123", bearing_degrees=90, proximity=0.5, overhead=True)
        )

        self.assertEqual(self.arrow_block(overhead), self.arrow_block(plain))

    def test_hidden_arrow_leaves_the_block_dark_without_reflowing_the_callsign(self) -> None:
        shown = self.render(DisplayPage("ASA123", bearing_degrees=90, proximity=0.5))
        hidden = self.render(
            DisplayPage("ASA123", bearing_degrees=90, proximity=0.5, arrow_visible=False)
        )

        self.assertEqual(sum(sum(row) for row in self.arrow_block(hidden)), 0)
        # The callsign must not shift when the arrow blinks off.
        for row in range(8):
            self.assertEqual(
                self.lit_columns(hidden, row, until=24),
                self.lit_columns(shown, row, until=24),
            )


class Hub75LayoutTests(unittest.TestCase):
    """Render to a fake panel so the 64x64 layout is checked, not assumed."""

    def renderer(self, width: int = 64, height: int = 64) -> tuple[Hub75Renderer, FakePanel]:
        panel = FakePanel(width, height)
        return Hub75Renderer(Hub75Settings(), DisplaySettings(), matrix=panel), panel

    def frame(self, page: DisplayPage, **size):
        renderer, panel = self.renderer(**size)
        renderer.render(page)
        return panel.frames[-1]

    def lit_rows(self, image) -> list[int]:
        pixels = image.load()
        return [
            row
            for row in range(image.height)
            if any(pixels[column, row] != (0, 0, 0) for column in range(image.width))
        ]

    def test_page_stacks_callsign_arrow_and_bar_down_the_panel(self) -> None:
        image = self.frame(DisplayPage("ASA123", bearing_degrees=0, proximity=0.5))
        rows = self.lit_rows(image)

        # Callsign near the top, bar on the bottom edge, arrow between them.
        self.assertLess(min(rows), 8)
        self.assertEqual(max(rows), image.height - 1)
        self.assertTrue(any(20 <= row <= 40 for row in rows))

    def test_proximity_bar_spans_the_full_width(self) -> None:
        image = self.frame(DisplayPage("ASA123", bearing_degrees=0, proximity=1.0))
        pixels = image.load()
        bottom = image.height - 1

        self.assertTrue(all(pixels[column, bottom] != (0, 0, 0) for column in range(image.width)))

        half = self.frame(DisplayPage("ASA123", bearing_degrees=0, proximity=0.5)).load()
        self.assertNotEqual(half[0, bottom], (0, 0, 0))
        self.assertEqual(half[image.width - 1, bottom], (0, 0, 0))

    def arrow_tip_degrees(self, renderer: Hub75Renderer, image) -> float:
        """Bearing of the lit pixel furthest from the dial centre, which is the tip."""
        pixels = image.load()
        center_x = renderer._dial_left + renderer._dial_size / 2
        center_y = renderer._dial_top + renderer._dial_size / 2
        tip = max(
            (
                ((x - center_x) ** 2 + (y - center_y) ** 2, x, y)
                for y in range(renderer._dial_top, renderer._dial_top + renderer._dial_size)
                for x in range(renderer._dial_left, renderer._dial_left + renderer._dial_size)
                if pixels[x, y] != (0, 0, 0)
            ),
        )
        return math.degrees(math.atan2(tip[1] - center_x, center_y - tip[2])) % 360

    def test_arrow_points_at_the_true_bearing_not_a_rounded_octant(self) -> None:
        renderer, panel = self.renderer()

        for bearing in (0, 22, 45, 90, 135, 180, 225, 270, 315, 340):
            with self.subTest(bearing=bearing):
                renderer.render(DisplayPage("ASA123", bearing_degrees=bearing))
                drawn = self.arrow_tip_degrees(renderer, panel.frames[-1])
                offset = abs((drawn - bearing + 180) % 360 - 180)
                self.assertLess(offset, 8)

    def test_small_panels_fall_back_to_the_octant_sprite(self) -> None:
        renderer, panel = self.renderer(32, 16)
        self.assertLess(renderer._dial_size, MINIMUM_VECTOR_ARROW)

        renderer.render(DisplayPage("ASA123", bearing_degrees=90))
        pixels = panel.frames[-1].load()
        drawn = tuple(
            tuple(
                1
                if pixels[
                    renderer._arrow_left + column * renderer._arrow_scale,
                    renderer._arrow_row + row * renderer._arrow_scale,
                ]
                != (0, 0, 0)
                else 0
                for column in range(ARROW_WIDTH)
            )
            for row in range(ARROW_HEIGHT)
        )
        expected = tuple(tuple(1 if cell == "#" else 0 for cell in row) for row in ARROW_SPRITES[2])
        self.assertEqual(drawn, expected)

    def test_hidden_arrow_leaves_the_middle_dark_without_moving_the_callsign(self) -> None:
        shown = self.frame(DisplayPage("ASA123", bearing_degrees=90, proximity=0.5))
        hidden = self.frame(
            DisplayPage("ASA123", bearing_degrees=90, proximity=0.5, arrow_visible=False)
        )

        self.assertLess(len(self.lit_rows(hidden)), len(self.lit_rows(shown)))
        self.assertEqual(min(self.lit_rows(hidden)), min(self.lit_rows(shown)))

    def test_overhead_recolours_the_arrow_rather_than_moving_it(self) -> None:
        renderer, panel = self.renderer()
        renderer.render(DisplayPage("ASA123", bearing_degrees=90))
        renderer.render(DisplayPage("ASA123", bearing_degrees=90, overhead=True))
        plain, overhead = panel.frames[-2], panel.frames[-1]

        self.assertEqual(
            self.arrow_tip_degrees(renderer, plain),
            self.arrow_tip_degrees(renderer, overhead),
        )
        self.assertNotEqual(self.arrow_colors(plain), self.arrow_colors(overhead))

    def arrow_colors(self, image) -> set:
        pixels = image.load()
        return {
            pixels[x, y]
            for y in range(20, 40)
            for x in range(image.width)
            if pixels[x, y] != (0, 0, 0)
        }

    def test_long_callsign_is_clipped_to_the_panel_width(self) -> None:
        image = self.frame(DisplayPage("QXE2372WAYTOOLONG", bearing_degrees=0))
        pixels = image.load()

        self.assertTrue(
            all(pixels[image.width - 1, row] == (0, 0, 0) for row in range(0, 16)),
        )

    def test_layout_stays_on_panel_for_every_supported_geometry(self) -> None:
        for width, height in ((64, 64), (64, 32), (32, 16), (128, 64)):
            with self.subTest(size=(width, height)):
                renderer, _ = self.renderer(width, height)
                arrow_top = min(renderer._arrow_row, renderer._dial_top)
                arrow_bottom = max(
                    renderer._arrow_row + ARROW_HEIGHT * renderer._arrow_scale,
                    renderer._dial_top + renderer._dial_size,
                )
                arrow_right = max(
                    renderer._arrow_left + ARROW_WIDTH * renderer._arrow_scale,
                    renderer._dial_left + renderer._dial_size,
                )

                # Headline, arrow, and bar are three bands that must not collide.
                self.assertGreaterEqual(arrow_top, renderer._arrow_top - renderer._margin)
                self.assertLessEqual(arrow_bottom, renderer._bar_top)
                self.assertLessEqual(arrow_right, width)

    @patch("balc_flights_led.display.time.sleep")
    def test_animations_emit_frames_and_close_clears_the_panel(self, sleep) -> None:
        renderer, panel = self.renderer()

        renderer.render(ArrivalAnimation("ASA123", bearing_degrees=45))
        renderer.render(MarqueePage("ASA123 B739 2.4NM SE"))
        renderer.render(IdleAnimation(seconds=0.2))
        renderer.close()

        self.assertGreater(len(panel.frames), 10)
        self.assertTrue(sleep.called)
        self.assertEqual(panel.cleared, 1)


class Hub75RadarTests(unittest.TestCase):
    """The radar is the reason for the panel, so its geometry is checked pixel by pixel."""

    RANGE = 10.0

    def renderer(self, width: int = 64, height: int = 64) -> tuple[Hub75Renderer, FakePanel]:
        panel = FakePanel(width, height)
        display = DisplaySettings(frame_seconds=0.01)
        return Hub75Renderer(Hub75Settings(), display, matrix=panel), panel

    def page(self, tracks: tuple[RadarTrack, ...], **overrides) -> RadarPage:
        fields: dict[str, Any] = {
            "range_nautical_miles": self.RANGE,
            "tracks": tracks,
            "label": "ASA123",
            "detail": ("B739 5500FT", "266KT CLB"),
            "distance_text": "5.0NM",
            "compass": "E",
            "trend": 1,
            "seconds": 0.01,
        }
        fields.update(overrides)
        return RadarPage(**fields)

    def render(self, page: RadarPage) -> tuple[Hub75Renderer, Any]:
        renderer, panel = self.renderer()
        with patch("balc_flights_led.display.time.sleep"):
            renderer.render(page)
        return renderer, panel.frames[-1]

    def pixels_matching(self, image, color: tuple[int, int, int]) -> set[tuple[int, int]]:
        loaded = image.load()
        return {
            (x, y) for y in range(image.height) for x in range(image.width) if loaded[x, y] == color
        }

    def test_a_contact_lands_at_its_bearing_and_range(self) -> None:
        track = RadarTrack("ASA123", 5.0, 90.0, trend=1)
        renderer, image = self.render(self.page((track,)))

        expected = renderer._radar_point(5.0, 90.0, self.RANGE)
        center_x, center_y = renderer._radar_center
        # Due east at half range: right of the origin, on its row.
        self.assertEqual(expected, (center_x + renderer._radar_radius // 2, center_y))
        self.assertIn(expected, self.pixels_matching(image, _dim(TREND_COLORS[1], 0.45)))

    def test_every_track_in_range_is_plotted_not_just_the_nearest(self) -> None:
        tracks = (
            RadarTrack("ONE", 2.0, 90.0, trend=1),
            RadarTrack("TWO", 5.0, 135.0, trend=0),
            RadarTrack("THREE", 8.0, 180.0, trend=-1),
        )
        renderer, image = self.render(self.page(tracks))

        for track in tracks:
            with self.subTest(track=track.label):
                point = renderer._radar_point(
                    track.distance_nautical_miles,
                    track.bearing_degrees,
                    self.RANGE,
                )
                lit = self.pixels_matching(
                    image,
                    _dim(TREND_COLORS[track.trend], RADAR_AFTERGLOW_FLOOR),
                )
                self.assertIn(point, lit)

    def test_vertical_rate_becomes_colour(self) -> None:
        climbing = RadarTrack("UP", 5.0, 90.0, trend=1)
        descending = RadarTrack("DOWN", 5.0, 180.0, trend=-1)
        _, image = self.render(self.page((climbing, descending)))

        self.assertTrue(self.pixels_matching(image, _dim(TREND_COLORS[1], RADAR_AFTERGLOW_FLOOR)))
        self.assertTrue(self.pixels_matching(image, _dim(TREND_COLORS[-1], RADAR_AFTERGLOW_FLOOR)))

    def test_traffic_beyond_the_range_ring_is_dropped(self) -> None:
        outside = RadarTrack("FAR", self.RANGE * 2, 90.0, trend=1)
        _, image = self.render(self.page((outside,)))

        self.assertEqual(self.pixels_matching(image, _dim(TREND_COLORS[1], 0.45)), set())

    def test_the_nearest_contact_gets_a_target_marker(self) -> None:
        plain = RadarTrack("ASA123", 5.0, 90.0, trend=1)
        renderer, without = self.render(self.page((plain,)))
        _, with_marker = self.render(self.page((RadarTrack("ASA123", 5.0, 90.0, 1, True),)))

        # Scoped to the dial: the distance readout is drawn in the same colour.
        center_x, center_y = renderer._radar_center
        radius = renderer._radar_radius
        in_dial = {
            (x, y)
            for x in range(center_x - radius, center_x + radius + 1)
            for y in range(center_y - radius, center_y + radius + 1)
        }

        self.assertEqual(self.pixels_matching(without, RADAR_TARGET_COLOR) & in_dial, set())
        self.assertEqual(len(self.pixels_matching(with_marker, RADAR_TARGET_COLOR) & in_dial), 4)

    def contact_ink(self, image, renderer, track, color) -> int:
        """Pixels of a contact's own colour around its plotted point."""
        point = renderer._radar_point(
            track.distance_nautical_miles,
            track.bearing_degrees,
            self.RANGE,
        )
        loaded = image.load()
        return sum(
            1
            for offset_x in range(-1, 3)
            for offset_y in range(-1, 3)
            if loaded[point[0] + offset_x, point[1] + offset_y] == color
        )

    def test_only_the_nearest_contact_gets_the_larger_dot(self) -> None:
        nearest = RadarTrack("NEAR", 3.0, 90.0, trend=1, nearest=True)
        other = RadarTrack("OTHER", 6.0, 180.0, trend=1)
        renderer, image = self.render(self.page((nearest, other)))
        color = _dim(TREND_COLORS[1], RADAR_AFTERGLOW_FLOOR)

        self.assertEqual(self.contact_ink(image, renderer, nearest, color), 4)
        self.assertEqual(self.contact_ink(image, renderer, other, color), 1)

    def test_trails_are_kept_for_the_nearest_only(self) -> None:
        nearest = RadarTrack("NEAR", 3.0, 90.0, trend=1, nearest=True)
        other = RadarTrack("OTHER", 6.0, 180.0, trend=1)
        renderer, panel = self.renderer()
        page = self.page((nearest, other))
        with patch("balc_flights_led.display.time.sleep"):
            renderer.render(page)
            renderer.render(page)

        # A second page deep in history, and the other contact is still one pixel.
        self.assertEqual(len(renderer._trails["NEAR"]), 2)
        lit = self.contact_ink(
            panel.frames[-1],
            renderer,
            other,
            _dim(TREND_COLORS[1], RADAR_AFTERGLOW_FLOOR),
        )
        self.assertEqual(lit, 1)

    def heading_block(self, image, renderer) -> tuple[tuple[int, ...], ...]:
        loaded = image.load()
        return tuple(
            tuple(
                1 if loaded[renderer._heading_left + column, row] != (0, 0, 0) else 0
                for column in range(ARROW_WIDTH)
            )
            for row in range(ARROW_HEIGHT)
        )

    def expected_sprite(self, octant: int) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(1 if cell == "#" else 0 for cell in row) for row in ARROW_SPRITES[octant]
        )

    def test_the_heading_sprite_fills_the_top_right_corner(self) -> None:
        track = RadarTrack("ASA123", 5.0, 90.0, trend=1)
        for octant, heading in enumerate(range(0, 360, 45)):
            with self.subTest(heading=heading):
                renderer, image = self.render(self.page((track,), heading_degrees=heading))
                self.assertEqual(
                    self.heading_block(image, renderer),
                    self.expected_sprite(octant),
                )

    def test_heading_is_the_aircraft_track_not_the_bearing_to_it(self) -> None:
        track = RadarTrack("ASA123", 5.0, 180.0, trend=1)
        renderer, image = self.render(self.page((track,), heading_degrees=0.0))

        # Due south of us, flying north: the sprite follows the heading.
        self.assertEqual(self.heading_block(image, renderer), self.expected_sprite(0))

    def test_a_missing_heading_leaves_the_corner_dark(self) -> None:
        track = RadarTrack("ASA123", 5.0, 90.0, trend=1)
        renderer, image = self.render(self.page((track,), heading_degrees=None))

        self.assertEqual(sum(sum(row) for row in self.heading_block(image, renderer)), 0)

    def test_a_long_callsign_is_clipped_rather_than_reaching_the_sprite(self) -> None:
        track = RadarTrack("ASA123", 5.0, 90.0, trend=1)
        renderer, image = self.render(
            self.page((track,), label="ABCDEFGHIJKL", heading_degrees=0.0)
        )

        self.assertEqual(self.heading_block(image, renderer), self.expected_sprite(0))

    def test_the_detail_block_sits_clear_of_the_dial(self) -> None:
        renderer, image = self.render(self.page((RadarTrack("ASA123", 5.0, 90.0),)))
        loaded = image.load()
        _, center_y = renderer._radar_center
        dial_top = center_y - renderer._radar_radius

        lit_rows = [
            row
            for row in range(image.height)
            if any(loaded[column, row] != (0, 0, 0) for column in range(image.width))
        ]
        self.assertLess(min(lit_rows), dial_top)
        # The callsign occupies the top rows and the dial reaches the bottom edge.
        self.assertGreaterEqual(max(lit_rows), center_y)

    def test_an_empty_radar_still_draws_rings_and_a_sweep(self) -> None:
        _, image = self.render(self.page((), label="NO FLT", detail=(), distance_text=""))
        loaded = image.load()

        self.assertTrue(
            any(
                loaded[column, row] != (0, 0, 0)
                for row in range(image.height)
                for column in range(image.width)
            )
        )

    def test_the_layout_stays_on_panel_for_every_supported_geometry(self) -> None:
        for width, height in ((64, 64), (64, 32), (128, 64)):
            with self.subTest(width=width, height=height):
                panel = FakePanel(width, height)
                renderer = Hub75Renderer(
                    Hub75Settings(),
                    DisplaySettings(frame_seconds=0.01),
                    matrix=panel,
                )
                with patch("balc_flights_led.display.time.sleep"):
                    renderer.render(self.page((RadarTrack("ASA123", 5.0, 90.0, 1, True),)))

                center_x, center_y = renderer._radar_center
                self.assertGreaterEqual(center_y - renderer._radar_radius, 0)
                self.assertLess(center_y + renderer._radar_radius, height)
                self.assertGreaterEqual(center_x - renderer._radar_radius, 0)
                self.assertLess(center_x + renderer._radar_radius, width)

    @patch("balc_flights_led.display.time.sleep")
    def test_the_arrival_sprite_wipes_the_radar_in_behind_it(self, sleep) -> None:
        renderer, panel = self.renderer()
        page = self.page((RadarTrack("ASA123", 5.0, 90.0, 1, True),))

        renderer.render(ArrivalAnimation("ASA123", page=page))
        wiped = panel.frames[-1]
        renderer.render(page)

        # The sprite passes over an unlit panel, then hands over to the dial.
        self.assertEqual(self.pixels_matching(panel.frames[0], TREND_COLORS[1]), set())
        self.assertEqual(
            self.pixels_matching(wiped, RADAR_TARGET_COLOR),
            self.pixels_matching(panel.frames[-1], RADAR_TARGET_COLOR),
        )

    @patch("balc_flights_led.display.time.sleep")
    def test_an_arrival_without_a_radar_page_still_reveals_the_callsign(self, sleep) -> None:
        renderer, panel = self.renderer()

        renderer.render(ArrivalAnimation("ASA123", bearing_degrees=90))

        self.assertGreater(len(panel.frames), 10)


class Hub75DriverTests(unittest.TestCase):
    """Guard the boundary with rpi-rgb-led-matrix, which cannot be installed in CI."""

    def stub_bindings(self) -> tuple[Any, list[Any]]:
        opened: list[Any] = []

        class FakeRGBMatrix:
            def __init__(self, options=None) -> None:
                opened.append(options)

        module = types.ModuleType("rgbmatrix")
        module.RGBMatrix = FakeRGBMatrix
        module.RGBMatrixOptions = FakeOptions
        return module, opened

    def test_every_option_set_exists_on_the_real_binding(self) -> None:
        module, opened = self.stub_bindings()
        settings = Hub75Settings(panel_type="FM6126A", brightness=70)

        with (
            patch.dict(sys.modules, {"rgbmatrix": module}),
            patch("balc_flights_led.display._onboard_audio_loaded", return_value=False),
        ):
            open_hub75(settings)

        options = opened[0]
        self.assertEqual(options.cols, 64)
        self.assertEqual(options.brightness, 70)
        self.assertEqual(options.panel_type, "FM6126A")
        self.assertTrue(options.drop_privileges)

    def test_loaded_onboard_audio_is_reported_before_the_driver_exits(self) -> None:
        module, opened = self.stub_bindings()

        with (
            patch.dict(sys.modules, {"rgbmatrix": module}),
            patch("balc_flights_led.display._onboard_audio_loaded", return_value=True),
            self.assertRaisesRegex(RuntimeError, "snd_bcm2835"),
        ):
            open_hub75(Hub75Settings())

        self.assertEqual(opened, [])

    def test_disabling_hardware_pulsing_sidesteps_the_audio_conflict(self) -> None:
        module, opened = self.stub_bindings()

        with (
            patch.dict(sys.modules, {"rgbmatrix": module}),
            patch("balc_flights_led.display._onboard_audio_loaded", return_value=True),
        ):
            open_hub75(Hub75Settings(disable_hardware_pulsing=True))

        self.assertEqual(len(opened), 1)


if __name__ == "__main__":
    unittest.main()
