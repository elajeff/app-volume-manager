import unittest
from unittest.mock import Mock

from app_volume_manager.process_list import ProcessRow, row_matches_search, row_values
from app_volume_manager.rules import AppRule
from app_volume_manager.selection import TemporaryTargets, plan_apply, plan_removal


def live_row(pid, executable="Discord.exe", signature="discord.exe|main", rule=None, volumes=(100,)):
    return ProcessRow(
        f"process:{executable.casefold()}:{pid}", executable, pid, 1, volumes, rule, True,
        process_signature=signature, process_role="Main process",
    )


def by_id(*rows):
    return {row.row_id: row for row in rows}


class PlanApplyTests(unittest.TestCase):
    def test_saved_row_keeps_its_scope_and_enabled_flag(self):
        rule = AppRule("Discord.exe", 70, enabled=False, process_signature="discord.exe|main", process_role="Main")
        row = ProcessRow("rule:x", "Discord.exe", None, 0, (), rule, False, process_signature=rule.process_signature)
        plan = plan_apply([row], by_id(row), [rule], 25, Mock())
        self.assertEqual(plan.rules, [AppRule("Discord.exe", 25, False, "discord.exe|main", "Main")])
        self.assertEqual(plan.persistent_count, 1)
        self.assertEqual(plan.temporary_keys, ())

    def test_checking_every_matching_process_saves_the_profile_without_asking(self):
        rows = [live_row(1), live_row(2)]
        confirm = Mock()
        plan = plan_apply(rows, by_id(*rows), [], 40, confirm)
        confirm.assert_not_called()
        self.assertEqual(plan.persistent_count, 1)
        self.assertEqual([rule.volume for rule in plan.rules], [40])
        self.assertEqual(plan.temporary_keys, ())

    def test_checking_some_matching_processes_asks_and_follows_the_answer(self):
        first, second = live_row(1), live_row(2)
        for save in (True, False):
            with self.subTest(save=save):
                confirm = Mock(return_value=save)
                plan = plan_apply([first], by_id(first, second), [], 40, confirm)
                confirm.assert_called_once_with(first, 2)
                self.assertEqual(plan.persistent_count, int(save))
                self.assertEqual(plan.temporary_keys, () if save else ((1, "discord.exe"),))

    def test_process_without_a_signature_is_only_targeted_temporarily(self):
        row = live_row(7, signature=None)
        plan = plan_apply([row, row], by_id(row), [], 10, Mock())
        self.assertEqual(plan.rules, [])
        self.assertEqual(plan.persistent_count, 0)
        self.assertEqual(plan.temporary_keys, ((7, "discord.exe"),))

    def test_existing_profile_rule_supersedes_temporary_targets(self):
        rule = AppRule("Discord.exe", 50, process_signature="discord.exe|main")
        row = live_row(3, rule=rule)
        other = live_row(4, "Spotify.exe", signature=None)
        plan = plan_apply([other], by_id(row, other), [rule], 10, Mock())
        self.assertEqual(plan.superseded_keys, frozenset({(3, "discord.exe")}))


class PlanRemovalTests(unittest.TestCase):
    def test_collects_rules_and_temporary_targets_of_the_selected_rows(self):
        rule = AppRule("Discord.exe", 70)
        temporary = TemporaryTargets()
        temporary.add((1, "spotify.exe"), 20, Mock())
        rows = [live_row(5, rule=rule), live_row(1, "Spotify.exe", signature=None)]
        plan = plan_removal(rows, temporary)
        self.assertEqual(plan.rules, (rule,))
        self.assertEqual(plan.temporary_keys, frozenset({(1, "spotify.exe")}))
        self.assertEqual(plan.descriptions(), [
            "Discord.exe — all processes using this app",
            "spotify.exe (PID 1) — temporary target",
        ])

    def test_nothing_to_remove_is_empty(self):
        self.assertTrue(plan_removal([live_row(9)], TemporaryTargets()).is_empty)


class TemporaryTargetsTests(unittest.TestCase):
    def test_prune_drops_exited_processes_only(self):
        targets = TemporaryTargets()
        running, exited = Mock(), Mock()
        running.is_running.return_value = True
        exited.is_running.return_value = False
        targets.add((1, "a.exe"), 10, running)
        targets.add((2, "b.exe"), 20, exited)
        self.assertEqual(targets.live(), {(1, "a.exe"): 10})
        self.assertIn((2, "b.exe"), targets)
        self.assertEqual(targets.prune(), {(1, "a.exe"): 10})
        self.assertNotIn((2, "b.exe"), targets)
        self.assertEqual(targets.get((1, "a.exe")), 10)


class RowTextTests(unittest.TestCase):
    def test_search_requires_every_term(self):
        row = live_row(42, rule=AppRule("Discord.exe", 70))
        self.assertTrue(row_matches_search(row, ""))
        self.assertTrue(row_matches_search(row, "DISCORD 42 app rule"))
        self.assertFalse(row_matches_search(row, "discord spotify"))

    def test_values_show_status_target_and_checkbox(self):
        row = live_row(42, rule=AppRule("Discord.exe", 70), volumes=(30, 50))
        self.assertEqual(row_values(row, True, None)[0], "☑")
        self.assertEqual(row_values(row, False, None)[5:], ("Mixed", "70%", "App rule"))
        self.assertEqual(row_values(row, False, 20)[6:], ("20%", "Temporary process target"))
        waiting = ProcessRow("rule:x", "Discord.exe", None, 0, (), AppRule("Discord.exe", 70), False)
        self.assertEqual(row_values(waiting, False, None)[2:4], ("—", "0"))
        self.assertEqual(row_values(waiting, False, None)[7], "Waiting for app audio")


if __name__ == "__main__":
    unittest.main()
