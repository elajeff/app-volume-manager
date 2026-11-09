"""Regression checks for temporary targets and saved-rule removal."""

import unittest
from unittest.mock import Mock, patch

from app_volume_manager.rules import AppRule
from app_volume_manager.settings import SettingsError
from app_volume_manager.volume_service import AudioSession
from tests.support import close_window, open_window

MESSAGEBOX = "app_volume_manager.ui.main_window.messagebox"
KEY = (123, "discord.exe")


def discord(set_volume=lambda _value: None, volume=100):
    return AudioSession("Discord.exe", "new-device", set_volume, process_id=123, current_volume=volume)


def running_process():
    return Mock(is_running=lambda: True)


def check_the_only_row(app):
    app.checked_rows.add(next(iter(app._all_row_info)))


class RuleActionTests(unittest.TestCase):
    def test_applying_to_another_app_keeps_the_temporary_volume(self):
        rule = AppRule("Discord.exe", 70, process_signature="discord.exe|main")
        session = discord()
        session.process_signature = rule.process_signature
        other = AudioSession(
            "Spotify.exe", "spotify", lambda _value: None, process_id=456,
            current_volume=100, process_signature="spotify.exe|main",
        )
        app = open_window(self, sessions=[session, other], rules=[rule])
        app.temporary.add(KEY, 20, running_process())
        app._scan_sessions()
        app.checked_rows.add(next(
            row.row_id for row in app._all_row_info.values() if row.executable == "Spotify.exe"
        ))
        app.target_volume_var.set(40)

        app.apply_to_selected()

        self.assertEqual(app.temporary.get(KEY), 20)
        self.assertEqual(session.current_volume, 20)

    def test_temporary_target_survives_audio_gap_but_expires_with_process(self):
        app = open_window(self)
        process = running_process()
        app.temporary.add(KEY, 20, process)
        app._scan_sessions(update_table=False)
        self.assertEqual(app.temporary.get(KEY), 20)
        calls = []
        session = discord(calls.append)
        app.backend.sessions = [session]
        app._scan_sessions(update_table=False)
        self.assertEqual(calls, [20])
        # psutil's retained Process object detects termination and PID reuse.
        process.is_running = lambda: False
        session.current_volume = 100
        app._scan_sessions(update_table=False)
        self.assertEqual(calls, [20])
        self.assertEqual(app.temporary.live(), {})
        self.assertNotIn(KEY, app.temporary)

    def test_temporary_selection_records_process_identity(self):
        app = open_window(self, sessions=[discord()])
        check_the_only_row(app)
        app.target_volume_var.set(20)
        process = running_process()
        with patch("app_volume_manager.selection.psutil.Process", return_value=process):
            app.apply_to_selected()
        self.assertEqual(app.temporary.get(KEY), 20)
        self.assertIs(app.temporary._processes[KEY], process)
        self.assertEqual(app.store.saved, [])

    def remove_selected(self, saved, confirmed):
        rule = AppRule("Discord.exe", 70) if saved else None
        app = open_window(self, sessions=[discord(volume=20)], rules=[rule] if rule else [])
        try:
            check_the_only_row(app)
            app.temporary.add(KEY, 20, running_process())
            with patch(f"{MESSAGEBOX}.askyesno", return_value=confirmed):
                app.remove_selected()
            return KEY in app.temporary, len(app.store.saved), list(app.rules)
        finally:
            close_window(app)

    def test_remove_clears_temporary_targets_with_or_without_saved_rule(self):
        for saved in (False, True):
            for confirmed in (False, True):
                with self.subTest(saved=saved, confirmed=confirmed):
                    still_targeted, saves, rules = self.remove_selected(saved, confirmed)
                    self.assertEqual(still_targeted, not confirmed)
                    self.assertEqual(saves, int(saved and confirmed))
                    if confirmed:
                        self.assertEqual(rules, [])

    def test_failed_saved_rule_removal_keeps_temporary_target(self):
        rule = AppRule("Discord.exe", 70)
        app = open_window(self, sessions=[discord(volume=20)], rules=[rule])
        check_the_only_row(app)
        app.temporary.add(KEY, 20, running_process())
        app.store.error = SettingsError("read only")
        with patch(f"{MESSAGEBOX}.askyesno", return_value=True), patch(f"{MESSAGEBOX}.showerror") as error:
            app.remove_selected()
        error.assert_called_once()
        self.assertEqual(app.rules, [rule])
        self.assertEqual(app.temporary.get(KEY), 20)


if __name__ == "__main__":
    unittest.main()
