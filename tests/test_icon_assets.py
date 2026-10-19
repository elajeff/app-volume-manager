import unittest
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class IconAssetTests(unittest.TestCase):
    def test_icons_and_windows_build_resources_are_valid(self):
        with Image.open(PROJECT_ROOT / "assets" / "app-icon.png") as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, image.height)
        with Image.open(PROJECT_ROOT / "assets" / "app-icon.ico") as image:
            self.assertEqual(image.format, "ICO")
            self.assertGreaterEqual(image.width, 32)
            self.assertGreaterEqual(image.height, 32)
        script = (PROJECT_ROOT / "build-windows.bat").read_text(encoding="utf-8")
        self.assertIn('--icon "assets\\app-icon.ico"', script)
        self.assertIn('--add-data "assets;assets"', script)
        self.assertIn('--name "App Volume Manager"', script)
        self.assertIn('dist\\app volume manager.zip', script)


if __name__ == "__main__":
    unittest.main()
