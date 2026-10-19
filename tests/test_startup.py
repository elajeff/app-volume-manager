import unittest
from unittest.mock import patch

from app_volume_manager import startup


class StartupTests(unittest.TestCase):
    def test_startup_is_disabled_and_cannot_be_enabled_off_windows(self):
        with patch("app_volume_manager.startup.os.name", "posix"):
            self.assertFalse(startup.is_startup_enabled())
            with self.assertRaises(OSError):
                startup.set_startup_enabled(True)

    def test_frozen_startup_command_launches_minimized(self):
        with patch("app_volume_manager.startup.sys.frozen", True, create=True), \
             patch("app_volume_manager.startup.sys.executable", r"C:\Apps\AppVolumeManager.exe"):
            command = startup._startup_command()
        self.assertIn("--minimized", command)
        self.assertIn("AppVolumeManager.exe", command)


if __name__ == "__main__":
    unittest.main()
