import tempfile
import textwrap
import unittest
from pathlib import Path

from balc_flights_led.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_loads_toml_and_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.toml"
            path.write_text(
                textwrap.dedent(
                    """
                    [location]
                    latitude = 47.6
                    longitude = -122.3

                    [display]
                    renderer = "matrix"

                    [matrix]
                    rotate = 2
                    """
                ),
                encoding="utf-8",
            )

            settings = load_settings(
                path,
                environ={"BFL_LATITUDE": "47.6175", "BFL_CONTRAST": "32"},
            )

        self.assertEqual(settings.location.latitude, 47.6175)
        self.assertEqual(settings.location.longitude, -122.3)
        self.assertEqual(settings.display.renderer, "matrix")
        self.assertEqual(settings.matrix.rotate, 2)
        self.assertEqual(settings.matrix.contrast, 32)

    def test_rejects_polling_faster_than_public_cache(self) -> None:
        with self.assertRaisesRegex(ValueError, "20-second cache"):
            load_settings(
                Path("does-not-exist.toml"),
                environ={"BFL_REFRESH_SECONDS": "10"},
            )

    def test_defaults_match_public_api_center_and_known_matrix(self) -> None:
        settings = load_settings(Path("does-not-exist.toml"), environ={})

        self.assertEqual(settings.location.latitude, 47.6175)
        self.assertEqual(settings.location.longitude, -122.305)
        self.assertEqual(settings.matrix.cascaded, 4)
        self.assertEqual(settings.matrix.block_orientation, -90)
        self.assertEqual(settings.matrix.rotate, 0)


if __name__ == "__main__":
    unittest.main()
