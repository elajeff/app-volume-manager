import unittest

from app_volume_manager.rules import AppRule, normalize_executable_name


class RuleTests(unittest.TestCase):
    def test_normalizes_names_and_matches_case_insensitively(self):
        self.assertEqual(normalize_executable_name("Discord"), "Discord.exe")
        self.assertEqual(normalize_executable_name(r"C:\Apps\Discord\Discord.exe"), "Discord.exe")
        self.assertEqual(AppRule("Discord.EXE", 50).key, "discord.exe")

    def test_validates_executable_and_volume(self):
        for value in (0, 100):
            self.assertEqual(AppRule("discord.exe", value).volume, value)
        for value in (-1, 101, 12.5, True, "50"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AppRule("discord.exe", value)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            AppRule("  ", 50)

    def test_process_specific_and_app_rules_have_distinct_keys(self):
        app_rule = AppRule("Discord.exe", 70)
        process_rule = AppRule(
            "Discord.exe", 15, process_signature="discord.exe|role=audio", process_role="Audio process"
        )
        self.assertNotEqual(app_rule.key, process_rule.key)
        self.assertTrue(process_rule.is_process_specific)


if __name__ == "__main__":
    unittest.main()
