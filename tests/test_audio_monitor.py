import unittest
from unittest.mock import Mock

from app_volume_manager.audio_monitor import AudioSessionMonitor, refresh_interval_ms
from app_volume_manager.volume_service import AudioSession


class AudioMonitorTests(unittest.TestCase):
    def test_new_session_is_wrapped_applied_and_signals_gui(self):
        session = AudioSession("discord.exe", "session-1", lambda _value: None)
        applied, changed = [], Mock()
        monitor = AudioSessionMonitor(
            wrap_session=lambda *_args: session,
            on_session_created=applied.append,
            on_change=changed,
        )
        monitor._new_session(object(), "device-1", "Speakers")
        self.assertEqual(applied, [session])
        changed.assert_called_once_with()

    def test_visible_and_hidden_refresh_intervals(self):
        self.assertEqual(refresh_interval_ms(True, True), 2_000)
        self.assertEqual(refresh_interval_ms(True, False), 2_000)
        self.assertEqual(refresh_interval_ms(False, True), 60_000)
        self.assertEqual(refresh_interval_ms(False, False), 5_000)


if __name__ == "__main__":
    unittest.main()
