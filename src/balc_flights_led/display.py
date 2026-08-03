from __future__ import annotations

import math
import string
import time
from typing import Any, Protocol

from .config import DisplaySettings, MatrixSettings
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

# Proportional fonts already leave a trailing blank column, so the indicator can
# start immediately after the measured text width. Seven-character callsigns are
# 28px wide, which leaves exactly this many columns.
MINIMUM_CELL_WIDTH = 4

# (row, columns per frame, starting column) for the idle drift.
IDLE_DOTS = ((1, 1, 0), (3, 2, 11), (5, 1, 21), (6, 3, 5))


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
        if item.trend is not None:
            details.append({1: "climbing", 0: "level", -1: "descending"}[item.trend])
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
        fitted_text = self._fit_text(page.text, width)
        text_width, _ = self._textsize(fitted_text, self._font)
        self._text(draw, (0, self._text_y), fitted_text, fill="white", font=self._font)

        if page.stale:
            draw.point((width - 1, 0), fill="white")
        if page.proximity is not None and self._strip_row is not None:
            self._draw_proximity_bar(draw, page.proximity)

        cell_left = text_width
        cell_width = width - cell_left - (2 if page.stale else 0)
        if cell_width >= MINIMUM_CELL_WIDTH:
            self._draw_indicator(draw, page, cell_left, cell_width)

    def _draw_proximity_bar(self, draw: Any, proximity: float) -> None:
        lit = round(min(1.0, max(0.0, proximity)) * self._device.width)
        if lit > 0:
            draw.line((0, self._strip_row, lit - 1, self._strip_row), fill="white")

    def _draw_indicator(self, draw: Any, page: DisplayPage, left: int, width: int) -> None:
        bottom = self._glyph_bottom
        if page.overhead:
            draw.rectangle((left, 0, left + width - 1, bottom), fill="white")
        ink = "black" if page.overhead else "white"

        if page.bearing_degrees is not None:
            self._draw_bearing_arrow(draw, page.bearing_degrees, left, width, bottom, ink)
        elif page.trend is not None:
            self._draw_trend(draw, page.trend, left, width, bottom, ink)

    @staticmethod
    def _draw_bearing_arrow(
        draw: Any,
        bearing_degrees: float,
        left: int,
        width: int,
        bottom: int,
        ink: str,
    ) -> None:
        center_x = left + (width - 1) / 2
        center_y = bottom / 2
        # Separate radii, so a narrow cell still uses the full glyph height.
        radius_x = (width - 1) / 2
        radius_y = bottom / 2

        angle = math.radians(bearing_degrees)
        along_x, along_y = math.sin(angle), -math.cos(angle)
        tip_x = round(center_x + along_x * radius_x)
        tip_y = round(center_y + along_y * radius_y)
        tail_x = round(center_x - along_x * radius_x)
        tail_y = round(center_y - along_y * radius_y)
        draw.line((tail_x, tail_y, tip_x, tip_y), fill=ink)

        # Barbs sit one step back from the tip, perpendicular to the shaft.
        back_x = tip_x - round(along_x)
        back_y = tip_y - round(along_y)
        perpendicular_x, perpendicular_y = round(math.cos(angle)), round(math.sin(angle))
        for sign in (1, -1):
            barb_x = back_x + sign * perpendicular_x
            barb_y = back_y + sign * perpendicular_y
            if left <= barb_x <= left + width - 1 and 0 <= barb_y <= bottom:
                draw.point((barb_x, barb_y), fill=ink)

    @staticmethod
    def _draw_trend(
        draw: Any,
        trend: int,
        left: int,
        width: int,
        bottom: int,
        ink: str,
    ) -> None:
        """Stacked chevrons; deliberately shaft-less so they never read as a bearing arrow."""
        center_x = left + (width - 1) // 2
        if trend == 0:
            middle = bottom // 2
            draw.line((left, middle, left + width - 1, middle), fill=ink)
            draw.line((left, middle + 2, left + width - 1, middle + 2), fill=ink)
            return

        step = 1 if trend > 0 else -1
        apexes = (0, 3) if trend > 0 else (bottom, bottom - 3)
        arm_offsets = (1, 2) if width >= 5 else (1,)
        for apex in apexes:
            draw.point((center_x, apex), fill=ink)
            for offset in arm_offsets:
                arm_y = apex + offset * step
                if center_x - offset >= left:
                    draw.point((center_x - offset, arm_y), fill=ink)
                if center_x + offset <= left + width - 1:
                    draw.point((center_x + offset, arm_y), fill=ink)

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
