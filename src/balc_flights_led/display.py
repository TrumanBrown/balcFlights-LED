from __future__ import annotations

import math
import string
import time
from pathlib import Path
from typing import Any, Protocol

from .config import DisplaySettings, Hub75Settings, MatrixSettings, Settings
from .presentation import (
    ArrivalAnimation,
    DisplayItem,
    DisplayPage,
    IdleAnimation,
    MarqueePage,
)

DISPLAY_TEST = 0x0F
SHUTDOWN = 0x0C
SHUTDOWN_RETRIES = 10

# Top-down aircraft, nose to the right, 8 wide by 7 tall.
PLANE_SPRITE = (
    "...#....",
    "...##...",
    "#######.",
    "...####.",
    "#######.",
    "...##...",
    "...#....",
)
SPRITE_WIDTH = len(PLANE_SPRITE[0])

# Characters whose ink rows decide where the callsign sits and how much of the
# matrix is left over for the indicator strip.
INK_SAMPLE = string.ascii_uppercase + string.digits

# Blank rows kept between the callsign and the proximity bar.
STRIP_GAP = 1

# The rightmost block is reserved for the bearing arrow, leaving 24px of
# callsign. Hand-drawn sprites are used because an arbitrary-angle arrow rounded
# into 8 pixels reads as scattered dots rather than a direction.
ARROW_WIDTH = 8
ARROW_HEIGHT = 7

# Indexed by compass octant, clockwise from north.
ARROW_SPRITES = (
    (  # N
        "...##...",
        "..####..",
        ".######.",
        "########",
        "...##...",
        "...##...",
        "...##...",
    ),
    (  # NE
        "...#####",
        "....####",
        ".....###",
        "....#...",
        "...#....",
        "..#.....",
        ".#......",
    ),
    (  # E
        "....#...",
        "....##..",
        "....###.",
        "########",
        "....###.",
        "....##..",
        "....#...",
    ),
    (  # SE
        ".#......",
        "..#.....",
        "...#....",
        "....#...",
        ".....###",
        "....####",
        "...#####",
    ),
    (  # S
        "...##...",
        "...##...",
        "...##...",
        "########",
        ".######.",
        "..####..",
        "...##...",
    ),
    (  # SW
        "......#.",
        ".....#..",
        "....#...",
        "...#....",
        "###.....",
        "####....",
        "#####...",
    ),
    (  # W
        "...#....",
        "..##....",
        ".###....",
        "########",
        ".###....",
        "..##....",
        "...#....",
    ),
    (  # NW
        "#####...",
        "####....",
        "###.....",
        "...#....",
        "....#...",
        ".....#..",
        "......#.",
    ),
)

# (row, columns per frame, starting column) for the idle drift.
IDLE_DOTS = ((1, 1, 0), (3, 2, 11), (5, 1, 21), (6, 3, 5))

# Colours for RGB panels. The monochrome MAX7219 ignores all of these.
TEXT_COLOR = (255, 255, 255)
STALE_COLOR = (255, 176, 0)
ARROW_COLOR = (0, 190, 255)
OVERHEAD_COLOR = (255, 110, 0)
IDLE_COLOR = (0, 110, 190)
# The proximity bar warms up as the aircraft closes in.
BAR_COLORS = ((0.5, (0, 200, 60)), (0.8, (255, 176, 0)), (1.0, (255, 40, 40)))

# A north-pointing arrow in unit space with y up, rotated to the true bearing on
# panels big enough to resolve one. Clockwise from the tip, which is the only
# vertex on the unit circle so the direction is unambiguous.
ARROW_POLYGON = (
    (0.0, 1.0),
    (0.62, 0.12),
    (0.24, 0.12),
    (0.24, -0.85),
    (-0.24, -0.85),
    (-0.24, 0.12),
    (-0.62, 0.12),
)
# Below this the vector arrow degrades into scattered pixels and the hand-drawn
# octant sprites read better.
MINIMUM_VECTOR_ARROW = 16


def force_max7219_off(device: Any, cascaded: int) -> None:
    for _ in range(SHUTDOWN_RETRIES):
        device.data([DISPLAY_TEST, 0] * cascaded)
        for row in range(1, 9):
            device.data([row, 0] * cascaded)
        device.data([SHUTDOWN, 0] * cascaded)
        time.sleep(0.02)


class PageRenderer(Protocol):
    def render(self, item: DisplayItem) -> None: ...

    def close(self) -> None: ...


class ConsoleRenderer:
    def render(self, item: DisplayItem) -> None:
        if isinstance(item, IdleAnimation):
            print(f"[idle {item.seconds:g}s]", flush=True)
            return
        if isinstance(item, ArrivalAnimation):
            print(f"[arrival] {item.text}", flush=True)
            return
        if isinstance(item, MarqueePage):
            print(f"[scroll] {item.text}", flush=True)
            return

        details = [item.text]
        if item.bearing_degrees is not None:
            details.append(f"bearing={item.bearing_degrees:.0f}")
        if item.proximity is not None:
            details.append(f"proximity={item.proximity:.0%}")
        if item.overhead:
            details.append("OVERHEAD")
        if item.stale:
            details.append("STALE")
        print(" | ".join(details), flush=True)

    def close(self) -> None:
        return None


class MultiRenderer:
    """Fan each item out to several renderers, in order."""

    def __init__(self, *renderers: PageRenderer) -> None:
        self._renderers = renderers

    def render(self, item: DisplayItem) -> None:
        for renderer in self._renderers:
            renderer.render(item)

    def close(self) -> None:
        for renderer in self._renderers:
            renderer.close()


class Max7219Renderer:
    def __init__(
        self,
        settings: MatrixSettings,
        display: DisplaySettings | None = None,
        *,
        device: Any = None,
    ) -> None:
        try:
            from luma.core.interface.serial import noop, spi
            from luma.core.legacy import show_message, text, textsize
            from luma.core.legacy.font import (
                ATARI_FONT,
                CP437_FONT,
                LCD_FONT,
                SINCLAIR_FONT,
                TINY_FONT,
                proportional,
            )
            from luma.core.render import canvas
            from luma.led_matrix.device import max7219
            from PIL import Image, ImageDraw
        except ImportError as error:
            raise RuntimeError(
                "MAX7219 dependencies are missing; install the project hardware dependencies"
            ) from error

        if device is None:
            serial = spi(
                port=settings.spi_port,
                device=settings.spi_device,
                gpio=noop(),
                bus_speed_hz=settings.spi_speed_hz,
            )
            device = max7219(
                serial,
                cascaded=settings.cascaded,
                block_orientation=settings.block_orientation,
                rotate=settings.rotate,
                blocks_arranged_in_reverse_order=settings.reverse_order,
                contrast=settings.contrast,
            )
        self._device = device
        self._display = display or DisplaySettings()
        self._canvas = canvas
        available_fonts = {
            "atari": ATARI_FONT,
            "tiny": TINY_FONT,
            "lcd": LCD_FONT,
            "cp437": CP437_FONT,
            "sinclair": SINCLAIR_FONT,
        }
        self._font = proportional(available_fonts[self._display.font])
        self._marquee_font = proportional(CP437_FONT)
        self._text = text
        self._textsize = textsize
        self._show_message = show_message

        ink_top, ink_bottom = self._measure_ink_rows(Image, ImageDraw)
        self._text_y = -ink_top
        self._glyph_bottom = ink_bottom - ink_top
        strip_row = self._glyph_bottom + 1 + STRIP_GAP
        self._strip_row = strip_row if strip_row < self._device.height else None

    def _measure_ink_rows(self, image_module: Any, draw_module: Any) -> tuple[int, int]:
        """Find which rows the chosen font actually inks, so the layout adapts to it."""
        height = self._device.height
        image = image_module.new("1", (self._device.width * 4, height))
        self._text(draw_module.Draw(image), (0, 0), INK_SAMPLE, fill="white", font=self._font)
        pixels = image.load()
        inked = [
            row
            for row in range(height)
            if any(pixels[column, row] for column in range(image.width))
        ]
        return (min(inked), max(inked)) if inked else (0, height - 1)

    @property
    def device(self) -> Any:
        """Exposed so hardware checks can write MAX7219 registers directly."""
        return self._device

    def render(self, item: DisplayItem) -> None:
        if isinstance(item, ArrivalAnimation):
            self._render_arrival(item)
        elif isinstance(item, MarqueePage):
            self._render_marquee(item)
        elif isinstance(item, IdleAnimation):
            self._render_idle(item)
        else:
            with self._canvas(self._device) as draw:
                self._draw_page(draw, item)

    def close(self) -> None:
        try:
            force_max7219_off(self._device, self._device.cascaded)
        finally:
            self._device.persist = True
            self._device.cleanup()

    def _render_marquee(self, item: MarqueePage) -> None:
        self._show_message(
            self._device,
            item.text,
            fill="white",
            font=self._marquee_font,
            scroll_delay=self._display.scroll_delay,
        )

    def _render_arrival(self, item: ArrivalAnimation) -> None:
        width = self._device.width
        height = self._device.height
        frame_seconds = self._display.frame_seconds

        for offset in range(-SPRITE_WIDTH, width + 1):
            with self._canvas(self._device) as draw:
                self._draw_sprite(draw, offset, width, height)
            time.sleep(frame_seconds)

        page = DisplayPage(
            text=item.text,
            bearing_degrees=item.bearing_degrees,
            overhead=item.overhead,
        )
        for revealed in range(0, width + 1, 2):
            with self._canvas(self._device) as draw:
                self._draw_page(draw, page)
                if revealed < width:
                    draw.rectangle((revealed, 0, width - 1, height - 1), fill="black")
            time.sleep(frame_seconds)

    def _render_idle(self, item: IdleAnimation) -> None:
        width = self._device.width
        frame_seconds = self._display.frame_seconds
        for step in range(max(1, round(item.seconds / frame_seconds))):
            with self._canvas(self._device) as draw:
                for row, speed, start in IDLE_DOTS:
                    draw.point(((start + step * speed) % width, row), fill="white")
            time.sleep(frame_seconds)

    def _draw_page(self, draw: Any, page: DisplayPage) -> None:
        width = self._device.width
        height = self._device.height
        has_arrow = page.bearing_degrees is not None
        # Status text such as OFFLINE needs the whole matrix; only a flight page
        # gives up the last block to the arrow.
        text_width = width - ARROW_WIDTH if has_arrow else width

        fitted_text = self._fit_text(page.text, text_width)
        self._text(draw, (0, self._text_y), fitted_text, fill="white", font=self._font)

        if page.proximity is not None and self._strip_row is not None:
            self._draw_proximity_bar(draw, page.proximity, text_width)
        if page.stale:
            draw.point((width - 1, height - 1), fill="white")
        if has_arrow and page.arrow_visible:
            self._draw_arrow(draw, page.bearing_degrees, width - ARROW_WIDTH)

    def _draw_proximity_bar(self, draw: Any, proximity: float, width: int) -> None:
        lit = round(min(1.0, max(0.0, proximity)) * width)
        if lit > 0:
            draw.line((0, self._strip_row, lit - 1, self._strip_row), fill="white")

    @staticmethod
    def _draw_arrow(draw: Any, bearing_degrees: float, left: int) -> None:
        """Draw the octant arrow pointing from the reference point to the aircraft."""
        for row, pattern in enumerate(ARROW_SPRITES[_octant(bearing_degrees)]):
            for column, cell in enumerate(pattern):
                if cell == "#":
                    draw.point((left + column, row), fill="white")

    def _fit_text(self, value: str, available_width: int) -> str:
        fitted = value
        while fitted and self._textsize(fitted, self._font)[0] > available_width:
            fitted = fitted[:-1]
        return fitted or "?"

    @staticmethod
    def _draw_sprite(draw: Any, x_offset: int, width: int, height: int) -> None:
        top = max(0, (height - len(PLANE_SPRITE)) // 2)
        for row, line in enumerate(PLANE_SPRITE):
            for column, pixel in enumerate(line):
                x = x_offset + column
                if pixel == "#" and 0 <= x < width:
                    draw.point((x, top + row), fill="white")


def open_hub75(settings: Hub75Settings) -> Any:
    """Build the RGBMatrix described by the configuration."""
    try:
        from rgbmatrix import RGBMatrix, RGBMatrixOptions
    except ImportError as error:
        raise RuntimeError(
            "HUB75 panels need the rpi-rgb-led-matrix Python bindings; "
            "see the README for the install steps"
        ) from error

    # The driver calls exit() rather than raising when it finds this module, so
    # the check is made here where the fix can be explained.
    if not settings.disable_hardware_pulsing and _onboard_audio_loaded():
        raise RuntimeError(
            "snd_bcm2835 is loaded and the HUB75 driver needs the same PWM hardware; "
            "blacklist onboard audio as described in the README, or set "
            "hub75.disable_hardware_pulsing = true"
        )

    options = RGBMatrixOptions()
    options.rows = settings.rows
    options.cols = settings.columns
    options.chain_length = settings.chain_length
    options.parallel = settings.parallel
    options.hardware_mapping = settings.hardware_mapping
    options.gpio_slowdown = settings.gpio_slowdown
    options.pwm_bits = settings.pwm_bits
    options.pwm_lsb_nanoseconds = settings.pwm_lsb_nanoseconds
    options.brightness = settings.brightness
    options.limit_refresh_rate_hz = settings.limit_refresh_rate_hz
    options.led_rgb_sequence = settings.led_rgb_sequence
    options.panel_type = settings.panel_type
    options.pixel_mapper_config = settings.pixel_mapper_config
    options.disable_hardware_pulsing = settings.disable_hardware_pulsing
    options.drop_privileges = settings.drop_privileges
    return RGBMatrix(options=options)


def _onboard_audio_loaded() -> bool:
    try:
        modules = Path("/proc/modules").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "snd_bcm2835" in modules


class Hub75Renderer:
    """Renderer for HUB75 RGB panels, such as the Waveshare 64x64.

    The panel is tall enough for a stacked layout rather than the single 8-row
    strip the MAX7219 chain gets: a scaled callsign, a large bearing arrow, and
    a full-width proximity bar.
    """

    def __init__(
        self,
        settings: Hub75Settings,
        display: DisplaySettings | None = None,
        *,
        matrix: Any = None,
    ) -> None:
        try:
            from luma.core.legacy import text, textsize
            from luma.core.legacy.font import (
                ATARI_FONT,
                CP437_FONT,
                LCD_FONT,
                SINCLAIR_FONT,
                TINY_FONT,
                proportional,
            )
            from PIL import Image, ImageDraw
        except ImportError as error:
            raise RuntimeError(
                "HUB75 dependencies are missing; install the project hardware dependencies"
            ) from error

        self._matrix = open_hub75(settings) if matrix is None else matrix
        self._frame = self._matrix.CreateFrameCanvas()
        self._display = display or DisplaySettings()
        self._image = Image
        self._image_draw = ImageDraw
        self._text = text
        self._textsize = textsize
        available_fonts = {
            "atari": ATARI_FONT,
            "tiny": TINY_FONT,
            "lcd": LCD_FONT,
            "cp437": CP437_FONT,
            "sinclair": SINCLAIR_FONT,
        }
        self._font = proportional(available_fonts[self._display.font])
        self._marquee_font = proportional(CP437_FONT)

        self._width = int(self._matrix.width)
        self._height = int(self._matrix.height)
        self._scale = max(1, self._height // 32)
        self._margin = self._scale
        self._bar_height = max(2, self._height // 16)
        self._bar_top = self._height - self._bar_height

        headline_height = self._glyph_height() * self._scale
        self._arrow_top = self._margin + headline_height + self._margin
        arrow_space = self._bar_top - self._margin - self._arrow_top

        # A square box keeps a rotated arrow on the panel at every bearing.
        self._dial_size = max(0, min(self._width - 2 * self._margin, arrow_space))
        self._dial_left = (self._width - self._dial_size) // 2
        self._dial_top = self._arrow_top + (arrow_space - self._dial_size) // 2

        self._arrow_scale = max(
            1,
            min(
                (self._width - 2 * self._margin) // ARROW_WIDTH,
                arrow_space // ARROW_HEIGHT,
            ),
        )
        arrow_height = ARROW_HEIGHT * self._arrow_scale
        self._arrow_left = (self._width - ARROW_WIDTH * self._arrow_scale) // 2
        # Clamped so a short panel crowds the arrow rather than drawing it over
        # the proximity bar or off the bottom edge.
        self._arrow_row = min(
            max(0, self._arrow_top + (arrow_space - arrow_height) // 2),
            max(0, self._bar_top - arrow_height),
        )

    @property
    def matrix(self) -> Any:
        """Exposed so hardware checks can drive the panel directly."""
        return self._matrix

    def render(self, item: DisplayItem) -> None:
        if isinstance(item, ArrivalAnimation):
            self._render_arrival(item)
        elif isinstance(item, MarqueePage):
            self._render_marquee(item)
        elif isinstance(item, IdleAnimation):
            self._render_idle(item)
        else:
            self._show(self._page_image(item))

    def close(self) -> None:
        self._matrix.Clear()

    def _glyph_height(self) -> int:
        layer = self._glyph_layer(INK_SAMPLE, self._font)
        return layer.height

    def _blank(self) -> Any:
        return self._image.new("RGB", (self._width, self._height))

    def _show(self, image: Any) -> None:
        self._frame.SetImage(image)
        self._frame = self._matrix.SwapOnVSync(self._frame)

    def _glyph_layer(self, value: str, font: Any, scale: int = 1) -> Any:
        """Render text to a 1-bit mask, trimmed to its ink and scaled up."""
        width = max(1, self._textsize(value, font)[0])
        layer = self._image.new("1", (width, 8))
        self._text(self._image_draw.Draw(layer), (0, 0), value, fill="white", font=font)
        box = layer.getbbox()
        if box is not None:
            layer = layer.crop(box)
        if scale > 1:
            layer = layer.resize(
                (layer.width * scale, layer.height * scale),
                self._image.Resampling.NEAREST,
            )
        return layer

    def _stamp(self, image: Any, layer: Any, position: tuple[int, int], color: Any) -> None:
        image.paste(self._image.new("RGB", layer.size, color), position, layer)

    def _fit_text(self, value: str, font: Any, available_width: int, scale: int) -> str:
        fitted = value
        while fitted and self._textsize(fitted, font)[0] * scale > available_width:
            fitted = fitted[:-1]
        return fitted or "?"

    def _page_image(self, page: DisplayPage) -> Any:
        image = self._blank()
        limit = self._width - 2 * self._margin

        fitted = self._fit_text(page.text, self._font, limit, self._scale)
        headline = self._glyph_layer(fitted, self._font, self._scale)
        self._stamp(
            image,
            headline,
            ((self._width - headline.width) // 2, self._margin),
            STALE_COLOR if page.stale else TEXT_COLOR,
        )

        if page.bearing_degrees is not None and page.arrow_visible:
            self._draw_arrow(
                image,
                page.bearing_degrees,
                OVERHEAD_COLOR if page.overhead else ARROW_COLOR,
            )

        if page.proximity is not None:
            self._draw_proximity_bar(image, page.proximity)
        if page.stale:
            self._image_draw.Draw(image).rectangle(
                (self._width - 2, 0, self._width - 1, 1),
                fill=STALE_COLOR,
            )
        return image

    def _draw_arrow(self, image: Any, bearing_degrees: float, color: Any) -> None:
        if self._dial_size < MINIMUM_VECTOR_ARROW:
            self._stamp_sprite(
                image,
                ARROW_SPRITES[_octant(bearing_degrees)],
                (self._arrow_left, self._arrow_row),
                self._arrow_scale,
                color,
            )
            return

        radius = self._dial_size / 2
        center_x = self._dial_left + radius
        center_y = self._dial_top + radius
        angle = math.radians(bearing_degrees % 360)
        sine, cosine = math.sin(angle), math.cos(angle)
        self._image_draw.Draw(image).polygon(
            [
                (
                    center_x + radius * (x * cosine + y * sine),
                    center_y - radius * (y * cosine - x * sine),
                )
                for x, y in ARROW_POLYGON
            ],
            fill=color,
        )

    def _stamp_sprite(
        self,
        image: Any,
        sprite: tuple[str, ...],
        position: tuple[int, int],
        scale: int,
        color: Any,
    ) -> None:
        left, top = position
        draw = self._image_draw.Draw(image)
        for row, pattern in enumerate(sprite):
            for column, cell in enumerate(pattern):
                if cell != "#":
                    continue
                x = left + column * scale
                y = top + row * scale
                draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=color)

    def _draw_proximity_bar(self, image: Any, proximity: float) -> None:
        clamped = min(1.0, max(0.0, proximity))
        lit = round(clamped * self._width)
        if lit <= 0:
            return
        color = next(color for threshold, color in BAR_COLORS if clamped <= threshold)
        self._image_draw.Draw(image).rectangle(
            (0, self._bar_top, lit - 1, self._height - 1),
            fill=color,
        )

    def _render_marquee(self, item: MarqueePage) -> None:
        layer = self._glyph_layer(item.text, self._marquee_font, self._scale)
        color = STALE_COLOR if item.stale else TEXT_COLOR
        top = (self._height - layer.height) // 2
        for offset in range(self._width, -layer.width - 1, -self._scale):
            image = self._blank()
            self._stamp(image, layer, (offset, top), color)
            self._show(image)
            time.sleep(self._display.scroll_delay)

    def _render_arrival(self, item: ArrivalAnimation) -> None:
        scale = self._arrow_scale
        sprite_width = SPRITE_WIDTH * scale
        top = (self._height - len(PLANE_SPRITE) * scale) // 2
        frame_seconds = self._display.frame_seconds

        for offset in range(-sprite_width, self._width + 1, scale):
            image = self._blank()
            self._stamp_sprite(image, PLANE_SPRITE, (offset, top), scale, TEXT_COLOR)
            self._show(image)
            time.sleep(frame_seconds)

        page = self._page_image(
            DisplayPage(
                text=item.text,
                bearing_degrees=item.bearing_degrees,
                overhead=item.overhead,
            )
        )
        step = max(2, self._width // 16)
        for revealed in range(0, self._width + 1, step):
            image = page.copy()
            if revealed < self._width:
                self._image_draw.Draw(image).rectangle(
                    (revealed, 0, self._width - 1, self._height - 1),
                    fill=(0, 0, 0),
                )
            self._show(image)
            time.sleep(frame_seconds)

    def _render_idle(self, item: IdleAnimation) -> None:
        frame_seconds = self._display.frame_seconds
        column_scale = max(1, self._width // 32)
        row_scale = max(1, self._height // 8)
        size = max(2, self._height // 16)
        for step in range(max(1, round(item.seconds / frame_seconds))):
            image = self._blank()
            draw = self._image_draw.Draw(image)
            for row, speed, start in IDLE_DOTS:
                x = ((start + step * speed) * column_scale) % self._width
                y = min(row * row_scale, self._height - size)
                draw.rectangle((x, y, x + size - 1, y + size - 1), fill=IDLE_COLOR)
            self._show(image)
            time.sleep(frame_seconds)


def _octant(bearing_degrees: float) -> int:
    return int((bearing_degrees % 360) / 45 + 0.5) % len(ARROW_SPRITES)


def create_matrix_renderer(settings: Settings) -> PageRenderer:
    """Build the renderer for whichever panel the configuration selects."""
    if settings.display.panel == "hub75":
        return Hub75Renderer(settings.hub75, settings.display)
    return Max7219Renderer(settings.matrix, settings.display)
