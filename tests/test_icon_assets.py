import unittest
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class IconAssetTests(unittest.TestCase):
    def test_icons_are_valid(self):
        with Image.open(PROJECT_ROOT / "assets" / "app-icon.png") as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, image.height)
        with Image.open(PROJECT_ROOT / "assets" / "app-icon.ico") as image:
            self.assertEqual(image.format, "ICO")
            self.assertGreaterEqual(image.width, 32)
            self.assertGreaterEqual(image.height, 32)


if __name__ == "__main__":
    unittest.main()
