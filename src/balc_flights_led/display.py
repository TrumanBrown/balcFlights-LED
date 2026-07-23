from __future__ import annotations

import math
from typing import Any, Protocol

from .config import MatrixSettings
from .presentation import DisplayPage


class PageRenderer(Protocol):
    def render(self, page: DisplayPage) -> None: ...

    def close(self) -> None: ...


class ConsoleRenderer:
    def render(self, page: DisplayPage) -> None:
        details = [page.text]
        if page.bearing_degrees is not None:
            details.append(f"bearing={page.bearing_degrees:.0f}")
        if page.stale:
            details.append("STALE")
        print(" | ".join(details), flush=True)

    def close(self) -> None:
        return None


class Max7219Renderer:
    def __init__(self, settings: MatrixSettings) -> None:
        try:
            from luma.core.interface.serial import noop, spi
            from luma.core.legacy import text, textsize
            from luma.core.legacy.font import TINY_FONT, proportional
            from luma.core.render import canvas
            from luma.led_matrix.device import max7219
        except ImportError as error:
            raise RuntimeError(
                "MAX7219 dependencies are missing; install the project hardware dependencies"
            ) from error

        serial = spi(port=settings.spi_port, device=settings.spi_device, gpio=noop())
        self._device = max7219(
            serial,
            cascaded=settings.cascaded,
            block_orientation=settings.block_orientation,
            rotate=settings.rotate,
            blocks_arranged_in_reverse_order=settings.reverse_order,
            contrast=settings.contrast,
        )
        self._canvas = canvas
        self._font = proportional(TINY_FONT)
        self._text = text
        self._textsize = textsize

    def render(self, page: DisplayPage) -> None:
        text_start = 8 if page.bearing_degrees is not None else 0
        available_width = self._device.width - text_start
        fitted_text = self._fit_text(page.text, available_width)
        text_width, _ = self._textsize(fitted_text, self._font)
        text_x = text_start + max(0, (available_width - text_width) // 2)

        with self._canvas(self._device) as draw:
            if page.bearing_degrees is not None:
                self._draw_bearing_arrow(draw, page.bearing_degrees)
            self._text(draw, (text_x, -1), fitted_text, fill="white", font=self._font)
            if page.stale:
                draw.point((self._device.width - 1, 0), fill="white")

    def close(self) -> None:
        self._device.clear()
        self._device.cleanup()

    def _fit_text(self, value: str, available_width: int) -> str:
        fitted = value
        while fitted and self._textsize(fitted, self._font)[0] > available_width:
            fitted = fitted[:-1]
        return fitted or "?"

    @staticmethod
    def _draw_bearing_arrow(draw: Any, bearing_degrees: float) -> None:
        angle = math.radians(bearing_degrees)
        center_x, center_y = 3, 4
        end_x = center_x + round(math.sin(angle) * 3)
        end_y = center_y - round(math.cos(angle) * 3)
        draw.line((center_x, center_y, end_x, end_y), fill="white")
        draw.point((center_x, center_y), fill="white")
        draw.point((end_x, end_y), fill="white")
