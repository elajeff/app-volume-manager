import unittest

from app_volume_manager.color_utils import hex_to_rgb, normalize_hex_color, rgb_to_hex


class SliderColorHelperTests(unittest.TestCase):
    def test_normalization_and_hex_rgb_round_trip(self):
        self.assertEqual(normalize_hex_color(" aB12cD "), "#AB12CD")
        self.assertEqual(hex_to_rgb("#1677FF"), (22, 119, 255))
        self.assertEqual(rgb_to_hex(22, 119, 255), "#1677FF")

    def test_invalid_hex_colors_and_rgb_channels_are_rejected(self):
        for value in ("blue", "#123", "#GGGGGG", "#12345678"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_hex_color(value)
        for channels in ((-1, 0, 0), (0, 256, 0), (1.5, 2, 3)):
            with self.subTest(channels=channels), self.assertRaises(ValueError):
                rgb_to_hex(*channels)


if __name__ == "__main__":
    unittest.main()
