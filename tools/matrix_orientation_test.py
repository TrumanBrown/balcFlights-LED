from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

SPI_SPEEDS_HZ = (500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calibrate a four-module MAX7219 matrix without calling the flight API."
    )
    parser.add_argument("--rotate", type=int, choices=(0, 2), default=2)
    parser.add_argument(
        "--block-orientation",
        type=int,
        choices=(-90, 0, 90, 180),
        default=-90,
    )
    parser.add_argument(
        "--reverse-order",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--contrast", type=int, choices=range(0, 256), default=64)
    parser.add_argument("--speed-hz", type=int, choices=SPI_SPEEDS_HZ, default=500_000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.seconds <= 0:
        raise SystemExit("--seconds must be greater than zero")

    from luma.core.interface.serial import noop, spi
    from luma.core.legacy import show_message, text, textsize
    from luma.core.legacy.font import CP437_FONT, proportional
    from luma.core.render import canvas
    from luma.led_matrix.device import max7219

    serial = spi(port=0, device=0, gpio=noop(), bus_speed_hz=arguments.speed_hz)
    device = max7219(
        serial,
        cascaded=4,
        block_orientation=arguments.block_orientation,
        rotate=arguments.rotate,
        blocks_arranged_in_reverse_order=arguments.reverse_order,
        contrast=arguments.contrast,
    )
    font = proportional(CP437_FONT)

    print(
        "Testing "
        f"rotate={arguments.rotate}, "
        f"block_orientation={arguments.block_orientation}, "
        f"reverse_order={arguments.reverse_order}, "
        f"speed_hz={arguments.speed_hz}",
        flush=True,
    )
    try:
        for module_index in range(4):
            print(f"Module {module_index + 1}: boxed digit", flush=True)
            with canvas(device) as draw:
                left = module_index * 8
                draw.rectangle((left, 0, left + 7, 7), outline="white")
                text(
                    draw,
                    (left + 1, 0),
                    str(module_index + 1),
                    fill="white",
                    font=font,
                )
            time.sleep(arguments.seconds)

        print("All modules: 1234", flush=True)
        label = "1234"
        label_width, _ = textsize(label, font)
        with canvas(device) as draw:
            text(
                draw,
                ((device.width - label_width) // 2, 0),
                label,
                fill="white",
                font=font,
            )
        time.sleep(arguments.seconds)

        print("Scrolling: ABCD 1234", flush=True)
        show_message(
            device,
            "ABCD 1234",
            fill="white",
            font=font,
            scroll_delay=0.08,
        )
    finally:
        device.clear()
        device.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
