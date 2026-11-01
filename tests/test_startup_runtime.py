"""Startup protection ordering and duplicate-launch behavior, without Windows APIs."""

import threading
import time
import unittest
from unittest.mock import Mock, patch

from app_volume_manager.audio_monitor import DEVICES_CHANGED, SESSIONS_CHANGED
from app_volume_manager.rules import AppRule
from app_volume_manager.settings import SettingsError
from app_volume_manager.single_instance import SingleInstance
from app_volume_manager.ui.main_window import VolumeManagerApp
from app_volume_manager.volume_service import AudioSession
from tests.support import FakeBackend, FakeRuleStore, close_window, fake_startup, open_window

MESSAGEBOX = "app_volume_manager.ui.main_window.messagebox"


class StartupRuntimeTests(unittest.TestCase):
    def test_restores_audio_before_ui_and_does_not_block_hidden_launch_on_preferences(self):
        events = []
        backend = FakeBackend([AudioSession(
            "Discord.exe", "voice", lambda value: events.append(("volume", value)), current_volume=100,
        )])
        backend.initialize = lambda: events.append("initialize")

        def monitor_factory(**_callbacks):
            monitor = Mock(healthy=True)
            monitor.start.side_effect = lambda: events.append("monitor")
            return monitor

        preferences = Mock()
        preferences.load_preferences.side_effect = SettingsError("broken appearance")
        build_ui = VolumeManagerApp._build_ui

        def recording_build_ui(app):
            events.append("ui")
            build_ui(app)

        with patch.object(VolumeManagerApp, "_build_ui", recording_build_ui), \
             patch(f"{MESSAGEBOX}.showwarning") as warning:
            app = open_window(
                self, start_minimized=True, backend=backend, store=FakeRuleStore([AppRule("Discord.exe", 15)]),
                preference_store=preferences, monitor_factory=monitor_factory,
            )
        self.assertEqual(events[:4], ["initialize", "monitor", ("volume", 15), "ui"])
        self.assertEqual(app.root.state(), "withdrawn")
        self.assertIn("broken appearance", app.status_var.get())
        warning.assert_not_called()

    def test_notification_failure_immediately_switches_hidden_polling_to_fallback(self):
        for healthy, expected in ((True, 60_000), (False, 5_000)):
            with self.subTest(healthy=healthy):
                app = open_window(self, monitor_factory=lambda **_callbacks: Mock(healthy=healthy))
                try:
                    app.window_visible = False
                    app._audio_event_queue.put(SESSIONS_CHANGED)
                    with patch.object(app, "_scan_sessions") as scan, patch.object(app, "_schedule_poll") as poll:
                        app._process_audio_events()
                    scan.assert_called_once_with(update_table=False)
                    poll.assert_called_once_with(expected)
                    self.assertEqual(app.backend.invalidated, 0)
                finally:
                    close_window(app)

    def test_device_events_make_the_next_sweep_list_devices_again(self):
        app = open_window(self)
        app.window_visible = False
        app._audio_event_queue.put(DEVICES_CHANGED)
        with patch.object(app, "_scan_sessions"), patch.object(app, "_schedule_poll"):
            app._process_audio_events()
        self.assertEqual(app.backend.invalidated, 1)


class SingleInstanceTests(unittest.TestCase):
    def test_duplicate_launch_signals_existing_copy_and_releases_handles(self):
        for existing, show in ((False, True), (True, True), (True, False)):
            with self.subTest(existing=existing, show=show):
                kernel = Mock()
                kernel.CreateEventW.return_value = 100
                kernel.CreateMutexW.return_value = 200
                kernel.WaitForSingleObject.return_value = 0
                with patch("ctypes.WinDLL", return_value=kernel, create=True), \
                     patch("ctypes.get_last_error", return_value=183 if existing else 0, create=True):
                    instance = SingleInstance()
                    self.assertEqual(instance.acquire(show_existing=show), not existing)
                    self.assertTrue(instance.show_requested())
                    instance.close()
                self.assertEqual(kernel.SetEvent.call_count, int(existing and show))
                self.assertEqual(kernel.CloseHandle.call_count, 2)


class StartupWorkerTests(unittest.TestCase):
    def test_hidden_sign_in_launch_checks_the_task_only_later(self):
        check = Mock(return_value=True)
        app = open_window(self, start_minimized=True, startup=fake_startup(check_startup=check))
        self.assertFalse(app._startup_checked)
        self.assertIsNotNone(app._startup_check_after_id)
        app.show_window()  # Opening the window early runs the check right away.
        self.wait_for_result(app)
        app._process_startup_results()
        check.assert_called_once_with()
        self.assertTrue(app.startup_var.get())
        app.show_window()
        self.assertEqual(check.call_count, 1)

    def wait_for_result(self, app):
        deadline = time.monotonic() + 2
        while app._startup_results.empty():
            if time.monotonic() > deadline:
                self.fail("the startup worker did not finish")
            time.sleep(0.01)

    def test_startup_worker_keeps_ui_free_and_delivers_success_or_failure_on_ui_poll(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                entered, release = threading.Event(), threading.Event()

                def update(_enabled):
                    entered.set()
                    if not release.wait(2):
                        raise RuntimeError("test worker was not released")
                    if fail:
                        raise OSError("Access denied")

                setter = Mock(side_effect=update)
                app = open_window(self, startup=fake_startup(set_startup_enabled=setter))
                try:
                    # The check the window starts on launch finishes first.
                    self.wait_for_result(app)
                    app._process_startup_results()
                    self.assertFalse(app._startup_busy)

                    with patch(f"{MESSAGEBOX}.showerror") as error:
                        app._start_startup_update(True)
                        self.assertTrue(entered.wait(1))
                        self.assertTrue(app._startup_busy)
                        self.assertTrue(app._startup_results.empty())
                        self.assertFalse(app.startup_var.get())
                        app._start_startup_update(False)  # Ignore a second click while busy.
                        setter.assert_called_once_with(True)
                        release.set()
                        self.wait_for_result(app)
                        app._process_startup_results()
                    self.assertFalse(app._startup_busy)
                    self.assertEqual(app.startup_var.get(), not fail)
                    self.assertEqual(error.call_count, int(fail))
                    self.assertTrue(app.startup_checkbutton.instate(["!disabled"]))
                finally:
                    release.set()
                    close_window(app)


if __name__ == "__main__":
    unittest.main()
