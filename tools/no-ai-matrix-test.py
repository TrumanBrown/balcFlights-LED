"""Hand-verified known-good MAX7219 baseline for this Pi.

Written and confirmed working directly on the hardware. Treat it as the
reference any driver change must still satisfy: SPI0/CE0 with luma's default
bus speed and contrast, four cascaded blocks, block_orientation -90.

    .venv/bin/python tools/no-ai-matrix-test.py
"""

import time

from luma.core.interface.serial import noop, spi
from luma.core.legacy import show_message, text
from luma.core.legacy.font import CP437_FONT, LCD_FONT, proportional
from luma.core.render import canvas
from luma.led_matrix.device import max7219

serial = spi(port=0, device=0, gpio=noop())
device = max7219(serial, cascaded=4, block_orientation=-90, blocks_arranged_in_reverse_order=False)

with canvas(device) as draw:
    draw.rectangle(device.bounding_box, outline="white", fill="black")

time.sleep(1)

with canvas(device) as draw:
    text(draw, (0, 0), "ABCD", fill="white", font=proportional(LCD_FONT))

time.sleep(1)

show_message(device, "Hello world", fill="white", font=proportional(CP437_FONT), scroll_delay=0.05)
