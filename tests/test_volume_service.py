import unittest

from app_volume_manager.rules import AppRule
from app_volume_manager.volume_service import AudioSession, VolumeRuleEngine


class VolumeRuleEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = VolumeRuleEngine()
        self.calls = []

    def session(self, executable="Discord.exe", session_id="session-1", error=None,
                pid=None, signature=None, role="Main process"):
        def set_volume(value):
            if error:
                raise RuntimeError(error)
            self.calls.append((session_id, value))
        return AudioSession(
            executable, session_id, set_volume, process_id=pid,
            process_signature=signature, process_role=role,
        )

    def test_applies_case_insensitive_rule_only_to_matching_enabled_processes(self):
        sessions = [self.session("DISCORD.EXE"), self.session("chrome.exe", "chrome"),
                    self.session("vlc.exe", "vlc")]
        rules = [AppRule("discord.exe", 40), AppRule("vlc.exe", 10, False)]
        result = self.engine.scan(sessions, rules)
        self.assertEqual(self.calls, [("session-1", 40)])
        self.assertEqual(result.applied_count, 1)
        self.assertIn("DISCORD.EXE", result.matched_applications)

    def test_only_reapplies_when_target_changes_or_reapply_is_requested(self):
        session = self.session()
        self.engine.scan([session], [AppRule("Discord.exe", 25)])
        self.engine.scan([session], [AppRule("Discord.exe", 25)])
        self.engine.scan([session], [AppRule("Discord.exe", 70)])
        self.engine.scan([session], [AppRule("Discord.exe", 70)], force=True)
        self.engine.scan([session], [])
        self.assertEqual(self.calls, [("session-1", 25), ("session-1", 70), ("session-1", 70)])

    def test_saved_rules_restore_external_resets_for_each_app_without_redundant_writes(self):
        for executable in ("Discord.exe", "Spotify.exe", "chrome.exe"):
            with self.subTest(executable=executable):
                engine = VolumeRuleEngine()
                calls = []
                session = AudioSession(executable, "session", calls.append, current_volume=100)
                rules = [AppRule(executable, 15)]
                engine.scan([session], rules)
                engine.scan([session], rules)
                session.current_volume = 100  # The app or Windows mixer reset it.
                engine.scan([session], rules)
                engine.scan([session], rules)
                self.assertEqual(calls, [15, 15])
                self.assertEqual(session.current_volume, 15)
                # Removing a rule stops enforcement.
                session.current_volume = 60
                engine.scan([session], [])
                self.assertEqual(calls, [15, 15])

    def test_notified_session_respects_temporary_override_and_restores_reset(self):
        calls = []
        session = AudioSession("Discord.exe", "session", calls.append,
                               process_id=123, current_volume=100)
        targets = {(123, "discord.exe"): 20}
        rules = [AppRule("Discord.exe", 70)]
        self.engine.apply_new_session(session, rules, targets)
        session.current_volume = 100
        self.engine.apply_new_session(session, rules, targets)
        self.assertEqual(calls, [20, 20])

    def test_adjusts_all_matching_sessions_and_continues_after_an_error(self):
        sessions = [self.session(session_id="bad", error="denied"),
                    self.session(session_id="good-1"), self.session(session_id="good-2")]
        result = self.engine.scan(sessions, [AppRule("Discord.exe", 20)])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(set(self.calls), {("good-1", 20), ("good-2", 20)})
        self.assertEqual(result.applied_count, 2)

    def test_failed_session_is_retried_and_closed_session_is_applied_after_return(self):
        rule = [AppRule("Discord.exe", 45)]
        failed = self.engine.scan([self.session(error="temporary COM error")], rule)
        self.assertEqual(len(failed.errors), 1)
        self.engine.scan([self.session()], rule)
        self.engine.scan([], rule)
        self.engine.scan([self.session()], rule)
        self.assertEqual(self.calls, [("session-1", 45), ("session-1", 45)])

    def test_new_session_is_applied_once_without_disturbing_existing_session(self):
        existing, new = self.session(session_id="existing"), self.session(session_id="new")
        rules = [AppRule("Discord.exe", 22)]
        self.engine.scan([existing], rules)
        immediate = self.engine.apply_new_session(new, rules)
        self.engine.scan([existing, new], rules)
        self.assertEqual(immediate.applied_count, 1)
        self.assertEqual(set(self.calls), {("existing", 22), ("new", 22)})
        self.assertEqual(len(self.calls), 2)

    def test_process_role_rule_overrides_app_rule_and_matches_after_pid_changes(self):
        signature = "discord.exe|type=utility;subtype=audio"
        rules = [AppRule("Discord.exe", 70),
                 AppRule("Discord.exe", 15, process_signature=signature, process_role="Audio utility")]
        main = self.session(session_id="main", pid=1, signature="discord.exe|main")
        utility = self.session(session_id="utility", pid=2, signature=signature, role="Audio utility")
        self.engine.scan([main, utility], rules)
        restarted = self.session(session_id="utility-restarted", pid=999,
                                 signature=signature, role="Audio utility")
        result = self.engine.scan([restarted], rules)
        self.assertEqual(self.calls, [("main", 70), ("utility", 15), ("utility-restarted", 15)])
        self.assertEqual(result.applied_count, 1)

    def test_temporary_target_changes_only_the_selected_process_instance(self):
        first = self.session(session_id="one", pid=1)
        second = self.session(session_id="two", pid=2)
        self.engine.scan([first, second], [AppRule("Discord.exe", 70)],
                         temporary_targets={(1, "discord.exe"): 20})
        self.assertEqual(set(self.calls), {("one", 20), ("two", 70)})


if __name__ == "__main__":
    unittest.main()
