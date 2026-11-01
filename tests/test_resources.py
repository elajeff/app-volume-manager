import sys
import unittest
from unittest.mock import patch

from app_volume_manager.ui.main_window import resource_path


class ResourcePathTests(unittest.TestCase):
    def test_source_run_finds_the_bundled_icons(self):
        for name in ("assets/app-icon.ico", "assets/app-icon.png"):
            with self.subTest(name=name):
                self.assertTrue(resource_path(name).is_file())

    def test_packaged_build_reads_from_the_extraction_folder(self):
        with patch.object(sys, "_MEIPASS", r"C:\Temp\_MEI1234", create=True):
            self.assertEqual(str(resource_path("assets/app-icon.ico")), r"C:\Temp\_MEI1234\assets\app-icon.ico")


if __name__ == "__main__":
    unittest.main()
