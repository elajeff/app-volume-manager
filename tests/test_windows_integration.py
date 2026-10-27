"""Real Windows startup APIs, using isolated names and cleaning up afterwards."""

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app_volume_manager import startup
from app_volume_manager.single_instance import SingleInstance


@unittest.skipUnless(sys.platform == "win32", "Windows APIs required")
class WindowsIntegrationTests(unittest.TestCase):
    def test_named_handles_prevent_duplicates_and_signal_existing_instance(self):
        name = "Local\\AppVolumeManager.Test." + uuid.uuid4().hex
        with patch("app_volume_manager.single_instance.MUTEX_NAME", name), \
             patch("app_volume_manager.single_instance.SHOW_EVENT_NAME", name + ".Show"):
            first, second = SingleInstance(), SingleInstance()
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                self.assertTrue(first.show_requested())
                self.assertFalse(first.show_requested())  # Auto-reset.
            finally:
                first.close()
                second.close()

    def test_register_query_and_remove_current_user_logon_task(self):
        name = "AppVolumeManager-Test-" + uuid.uuid4().hex
        executable = Path(sys.executable)
        # The task is never run. Use the current interpreter to validate quoting
        # and scheduler registration without depending on the repository path.
        with patch.object(startup, "_task_name", return_value=name), \
             patch.object(startup, "_startup_parts", return_value=(str(executable), "--version", str(executable.parent))), \
             patch.object(startup, "_remove_legacy"), \
             patch.object(startup, "_legacy_enabled", return_value=False):
            try:
                self.assertFalse(startup.is_startup_enabled())
                startup.set_startup_enabled(True)
                self.assertTrue(startup.is_startup_enabled())
            finally:
                startup.set_startup_enabled(False)
            self.assertFalse(startup.is_startup_enabled())
