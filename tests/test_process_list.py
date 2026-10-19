import unittest

from app_volume_manager.process_list import build_process_rows
from app_volume_manager.rules import AppRule
from app_volume_manager.volume_service import AudioSession


class ProcessListTests(unittest.TestCase):
    def session(self, executable="Discord.exe", session_id="device-1", pid=120, volume=35,
                signature=None, role="Main process"):
        return AudioSession(
            executable, session_id, lambda _value: None, process_id=pid, current_volume=volume,
            process_signature=signature, process_role=role,
        )

    def test_groups_sessions_for_one_pid_and_keeps_separate_instances(self):
        rows = build_process_rows(
            [self.session(session_id="one"), self.session(session_id="two", volume=35),
             self.session(session_id="other", pid=999),
             self.session(session_id="unknown-1", pid=None), self.session(session_id="unknown-2", pid=None)],
            [AppRule("Discord.exe", 25)],
        )
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({row.row_id for row in rows}), 4)
        by_pid = {row.process_id: row for row in rows if row.process_id is not None}
        self.assertEqual(by_pid[120].session_count, 2)
        self.assertEqual(by_pid[120].current_volumes, (35,))
        self.assertEqual(by_pid[999].session_count, 1)
        self.assertNotEqual(by_pid[120].row_id, by_pid[999].row_id)
        self.assertTrue(all(row.rule.volume == 25 for row in rows))

    def test_saved_rule_waits_until_session_appears_without_duplicate_active_row(self):
        rule = AppRule("Discord.exe", 25)
        waiting = build_process_rows([], [rule])
        active = build_process_rows([self.session("DISCORD.EXE")], [rule])
        self.assertEqual((len(waiting), waiting[0].active, waiting[0].session_count), (1, False, 0))
        self.assertEqual((len(active), active[0].active, active[0].rule.volume), (1, True, 25))

    def test_active_processes_are_listed_before_waiting_rules(self):
        rows = build_process_rows([self.session()], [AppRule("vlc.exe", 60)])
        self.assertTrue(rows[0].active)
        self.assertFalse(rows[1].active)

    def test_process_role_rule_overrides_app_rule_only_for_matching_instance(self):
        signature = "discord.exe|type=utility;subtype=audio"
        rows = build_process_rows(
            [self.session(pid=120, signature="discord.exe|main"),
             self.session(session_id="utility", pid=999, signature=signature, role="Audio utility")],
            [AppRule("Discord.exe", 70),
             AppRule("Discord.exe", 15, process_signature=signature, process_role="Audio utility")],
        )
        by_pid = {row.process_id: row for row in rows}
        self.assertEqual((by_pid[120].rule.volume, by_pid[999].rule.volume), (70, 15))
        self.assertTrue(by_pid[999].rule.is_process_specific)


if __name__ == "__main__":
    unittest.main()
