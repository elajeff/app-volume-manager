import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app_volume_manager import startup


class StartupTests(unittest.TestCase):
    def test_startup_cannot_be_enabled_off_windows(self):
        with patch.object(startup.os, "name", "posix"):
            with self.assertRaises(OSError):
                startup.set_startup_enabled(True)

    def test_frozen_startup_command_launches_minimized(self):
        with patch.object(startup.sys, "frozen", True, create=True), \
             patch.object(startup.sys, "executable", r"C:\Apps\AppVolumeManager.exe"):
            command = startup._startup_command()
        self.assertIn("--minimized", command)
        self.assertIn("AppVolumeManager.exe", command)

    def test_enable_disable_and_failed_registration_preserve_legacy_when_needed(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), patch.object(startup.os, "name", "nt"), \
                 patch.object(startup, "_run_task_command") as run, \
                 patch.object(startup, "_remove_legacy") as remove:
                startup.set_startup_enabled(enabled)
                run.assert_called_once_with("enable" if enabled else "disable")
                remove.assert_called_once_with()
        with patch.object(startup.os, "name", "nt"), \
             patch.object(startup, "_run_task_command", side_effect=OSError("Access denied")), \
             patch.object(startup, "_remove_legacy") as remove:
            with self.assertRaisesRegex(OSError, "Access denied"):
                startup.set_startup_enabled(True)
            remove.assert_not_called()

    def test_native_command_preserves_paths_and_returns_windows_errors(self):
        parts = (r"C:\Apps\Manager's folder\manager.exe", "--minimized", "C:\\Apps\\Δοκιμή")
        for returncode, stderr in ((0, ""), (1, "The task could not be registered")):
            with self.subTest(returncode=returncode), \
                 patch.object(startup, "_startup_parts", return_value=parts), \
                 patch.dict(startup.os.environ, {"SystemRoot": "C:\\Windows"}), \
                 patch.object(startup.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
                 patch.object(startup.subprocess, "run", return_value=SimpleNamespace(
                     returncode=returncode, stdout="true\n", stderr=stderr,
                 )) as run:
                if returncode:
                    with self.assertRaisesRegex(OSError, stderr):
                        startup._run_task_command("enable")
                else:
                    self.assertEqual(startup._run_task_command("query"), "true")
                args = run.call_args.args[0]
                script = base64.b64decode(args[-1]).decode("utf-16-le")
                encoded_request = script.split("FromBase64String('", 1)[1].split("')", 1)[0]
                request = json.loads(base64.b64decode(encoded_request))
                self.assertEqual((request["executable"], request["arguments"], request["directory"]), parts)
                self.assertNotIn("shell", run.call_args.kwargs)
                self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)

    def test_native_command_timeout_becomes_a_readable_error(self):
        from subprocess import TimeoutExpired
        with patch.object(startup, "_startup_parts", return_value=("manager.exe", "--minimized", "C:\\Apps")), \
             patch.dict(startup.os.environ, {"SystemRoot": "C:\\Windows"}), \
             patch.object(startup.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True), \
             patch.object(startup.subprocess, "run", side_effect=TimeoutExpired("powershell", 20)) as run:
            with self.assertRaisesRegex(OSError, "timed out after 20 seconds"):
                startup._run_task_command("enable")
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_check_upgrades_legacy_entries_and_outdated_tasks(self):
        cases = (
            # legacy Run entry, task query result, reported state, task commands run
            (True, None, True, []),
            (False, "true", True, ["query"]),
            (False, "outdated", True, ["query", "enable"]),
            (False, "false", False, ["query"]),
        )
        for legacy, state, expected, commands in cases:
            with self.subTest(legacy=legacy, state=state), patch.object(startup.os, "name", "nt"), \
                 patch.object(startup, "_legacy_enabled", return_value=legacy), \
                 patch.object(startup, "set_startup_enabled") as register, \
                 patch.object(startup, "_run_task_command", return_value=state) as run:
                self.assertEqual(startup.check_startup(), expected)
                self.assertEqual(register.call_count, int(legacy))
                self.assertEqual([call.args[0] for call in run.call_args_list], commands)

    def test_check_is_a_no_op_off_windows(self):
        with patch.object(startup.os, "name", "posix"), patch.object(startup, "_run_task_command") as run:
            self.assertFalse(startup.check_startup())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
