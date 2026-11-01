import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app_volume_manager.ui.tray import start_tray_icon

ICON = Path(__file__).resolve().parents[1] / "assets" / "app-icon.png"


class TrayTests(unittest.TestCase):
    def test_menu_has_open_reapply_and_exit_and_runs_detached(self):
        pystray = Mock()
        on_open, on_reapply, on_exit = Mock(), Mock(), Mock()
        with patch.dict(sys.modules, {"pystray": pystray}):
            icon = start_tray_icon("App Title", ICON, on_open, on_reapply, on_exit)
        pystray.MenuItem.assert_any_call("Open", on_open, default=True)
        pystray.MenuItem.assert_any_call("Reapply saved volumes", on_reapply)
        pystray.MenuItem.assert_any_call("Exit", on_exit)
        name, _image, title, _menu = pystray.Icon.call_args.args
        self.assertEqual((name, title), ("AppVolumeManager", "App Title"))
        icon.run_detached.assert_called_once_with()

    def test_startup_failure_is_raised_to_the_caller(self):
        pystray = Mock()
        pystray.Icon.side_effect = RuntimeError("no tray host")
        with patch.dict(sys.modules, {"pystray": pystray}), self.assertRaises(RuntimeError):
            start_tray_icon("App Title", ICON, Mock(), Mock(), Mock())


if __name__ == "__main__":
    unittest.main()
