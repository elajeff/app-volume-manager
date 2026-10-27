"""Regression checks for temporary targets and saved-rule removal."""

import unittest
from unittest.mock import Mock, patch

from app import VolumeManagerApp
from app_volume_manager.process_list import ProcessRow
from app_volume_manager.rules import AppRule
from app_volume_manager.volume_service import AudioSession, VolumeRuleEngine


class RuleActionTests(unittest.TestCase):
    def make_app(self):
        app = VolumeManagerApp.__new__(VolumeManagerApp)
        app._closing, app.audio_ready, app.window_visible = False, True, False
        app.backend = Mock(last_warnings=[])
        app.backend.get_sessions.return_value = []
        app.rules, app.engine = [], VolumeRuleEngine()
        app.temporary_process_targets, app.temporary_processes = {}, {}
        app.store, app.status_var, app._refresh_table = Mock(), Mock(), Mock()
        return app

    def test_temporary_target_survives_audio_gap_but_expires_with_process(self):
        app = self.make_app()
        key = (123, "discord.exe")
        process = Mock(is_running=lambda: True)
        app.temporary_process_targets[key] = 20
        app.temporary_processes[key] = process
        app._scan_sessions(update_table=False)
        self.assertEqual(app.temporary_process_targets[key], 20)
        calls = []
        session = AudioSession("Discord.exe", "new-device", calls.append, process_id=123, current_volume=100)
        app.backend.get_sessions.return_value = [session]
        app._scan_sessions(update_table=False)
        self.assertEqual(calls, [20])
        # psutil's retained Process object detects termination and PID reuse.
        process.is_running = lambda: False
        session.current_volume = 100
        app._scan_sessions(update_table=False)
        self.assertEqual(calls, [20])
        self.assertEqual(app.temporary_process_targets, {})
        self.assertEqual(app.temporary_processes, {})

    def test_temporary_selection_records_process_identity(self):
        app = self.make_app()
        row = ProcessRow("discord", "Discord.exe", 123, 1, (100,), None, True)
        app._selected_rows = lambda: [row]
        app._row_info = app._all_row_info = {row.row_id: row}
        app.target_volume_var = Mock(get=lambda: 20)
        process = Mock(is_running=lambda: True)
        with patch("app.psutil.Process", return_value=process):
            app.apply_to_selected()
        key = (123, "discord.exe")
        self.assertEqual(app.temporary_process_targets[key], 20)
        self.assertIs(app.temporary_processes[key], process)
        app.store.save_rules.assert_not_called()

    def test_remove_clears_temporary_targets_with_or_without_saved_rule(self):
        for saved in (False, True):
            for confirmed in (False, True):
                with self.subTest(saved=saved, confirmed=confirmed):
                    app = self.make_app()
                    rule = AppRule("Discord.exe", 70) if saved else None
                    app.rules = [rule] if rule else []
                    row = ProcessRow("discord", "Discord.exe", 123, 1, (20,), rule, True)
                    app._selected_rows = lambda: [row]
                    key = (123, "discord.exe")
                    app.temporary_process_targets[key] = 20
                    app.temporary_processes[key] = Mock()
                    with patch("app.messagebox.askyesno", return_value=confirmed):
                        app.remove_selected()
                    self.assertEqual(key in app.temporary_process_targets, not confirmed)
                    self.assertEqual(key in app.temporary_processes, not confirmed)
                    self.assertEqual(app.store.save_rules.call_count, int(saved and confirmed))
                    if confirmed:
                        self.assertEqual(app.rules, [])

    def test_failed_saved_rule_removal_keeps_temporary_target(self):
        from app_volume_manager.settings import SettingsError
        app = self.make_app()
        rule = AppRule("Discord.exe", 70)
        app.rules = [rule]
        app._selected_rows = lambda: [ProcessRow("discord", "Discord.exe", 123, 1, (20,), rule, True)]
        key = (123, "discord.exe")
        app.temporary_process_targets[key] = 20
        app.temporary_processes[key] = Mock()
        app.store.save_rules.side_effect = SettingsError("read only")
        with patch("app.messagebox.askyesno", return_value=True), patch("app.messagebox.showerror"):
            app.remove_selected()
        self.assertEqual(app.rules, [rule])
        self.assertEqual(app.temporary_process_targets[key], 20)
