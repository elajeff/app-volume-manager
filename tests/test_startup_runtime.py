"""Startup protection ordering and duplicate-launch behavior, without Windows APIs."""

import unittest
from unittest.mock import Mock, patch

from app import VolumeManagerApp
from app_volume_manager.rules import AppRule
from app_volume_manager.settings import SettingsError
from app_volume_manager.single_instance import SingleInstance
from app_volume_manager.volume_service import AudioSession


class StartupRuntimeTests(unittest.TestCase):
    def test_restores_audio_before_ui_and_does_not_block_hidden_launch_on_preferences(self):
        events = []
        root = Mock()
        backend = Mock()
        backend.initialize.side_effect = lambda: events.append("initialize")
        backend.get_sessions.return_value = [AudioSession(
            "Discord.exe", "voice", lambda value: events.append(("volume", value)), current_volume=100,
        )]
        store, preferences, monitor = Mock(), Mock(), Mock()
        store.load_rules.return_value = [AppRule("Discord.exe", 15)]
        preferences.load_preferences.side_effect = SettingsError("broken appearance")
        monitor.start.side_effect = lambda: events.append("monitor")

        def build_ui(app):
            events.append("ui")
            app.status_var, app.startup_var, app.startup_status_var = Mock(), Mock(), Mock()

        with patch("app.WindowsAudioBackend", return_value=backend), \
             patch("app.SettingsStore", return_value=store), \
             patch("app.PreferenceStore", return_value=preferences), \
             patch("app.AudioSessionMonitor", return_value=monitor), \
             patch.object(VolumeManagerApp, "_start_startup_update"), \
             patch.object(VolumeManagerApp, "_set_window_icon"), \
             patch.object(VolumeManagerApp, "_apply_theme"), \
             patch.object(VolumeManagerApp, "_build_ui", build_ui), \
             patch.object(VolumeManagerApp, "_start_tray_icon"), \
             patch("app.messagebox.showwarning") as warning:
            VolumeManagerApp(root, start_minimized=True)
        self.assertEqual(events[:4], ["initialize", "monitor", ("volume", 15), "ui"])
        root.withdraw.assert_called_once_with()
        warning.assert_not_called()

    def test_notification_failure_immediately_switches_hidden_polling_to_fallback(self):
        import queue
        for ready, error, expected in ((True, None, 60_000), (False, "disconnected", 5_000)):
            with self.subTest(ready=ready):
                app = VolumeManagerApp.__new__(VolumeManagerApp)
                app.root = Mock()
                app._closing = False
                app.window_visible = False
                app.audio_monitor = Mock(is_ready=ready, last_error=error)
                app._audio_event_queue = queue.SimpleQueue()
                app._audio_event_queue.put(True)
                app._scan_sessions = Mock()
                app._schedule_poll = Mock()
                app._process_audio_events()
                app._scan_sessions.assert_called_once_with(update_table=False)
                app._schedule_poll.assert_called_once_with(expected)

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
    def test_startup_worker_keeps_ui_free_and_delivers_success_or_failure_on_ui_poll(self):
        import queue
        import threading
        for fail in (False, True):
            with self.subTest(fail=fail):
                app = VolumeManagerApp.__new__(VolumeManagerApp)
                app._startup_busy, app._startup_enabled, app.window_visible = False, False, True
                app._startup_results = queue.SimpleQueue()
                app.startup_checkbutton, app.startup_status_var = Mock(), Mock()
                app.startup_var, app.status_var = Mock(), Mock()
                entered, release = threading.Event(), threading.Event()
                workers = []
                real_thread = threading.Thread

                def start_thread(**kwargs):
                    worker = real_thread(**kwargs)
                    workers.append(worker)
                    return worker

                def update(_enabled):
                    entered.set()
                    if not release.wait(2):
                        raise RuntimeError("test worker was not released")
                    if fail:
                        raise OSError("Access denied")

                with patch("app.set_startup_enabled", side_effect=update) as setter, \
                     patch("app.threading.Thread", side_effect=start_thread), \
                     patch("app.messagebox.showerror") as error:
                    try:
                        app._start_startup_update(True)
                        self.assertTrue(entered.wait(1))
                        self.assertTrue(app._startup_busy)
                        self.assertTrue(app._startup_results.empty())
                        app.startup_var.set.assert_not_called()
                        app._start_startup_update(False)  # Ignore a second click while busy.
                        setter.assert_called_once_with(True)
                    finally:
                        release.set()
                        for worker in workers:
                            worker.join(timeout=2)
                    app._process_startup_results()
                    self.assertFalse(app._startup_busy)
                    app.startup_var.set.assert_called_once_with(not fail)
                    self.assertEqual(error.call_count, int(fail))
                    app.startup_checkbutton.state.assert_any_call(["!disabled"])
