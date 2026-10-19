import json
import tempfile
import unittest
from pathlib import Path

from app_volume_manager.rules import AppRule
from app_volume_manager.settings import SettingsError, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "settings.json"
        self.store = SettingsStore(self.path)

    def test_missing_file_and_rule_round_trip(self):
        self.assertEqual(self.store.load_rules(), [])
        rules = [
            AppRule("Discord.exe", 70),
            AppRule("Discord.exe", 15, process_signature="discord.exe|role=audio", process_role="Audio process"),
            AppRule("vlc.exe", 65, False),
        ]
        self.store.save_rules(rules)
        self.assertEqual(self.store.load_rules(), rules)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["rules"]), 3)

    def test_malformed_or_unsupported_settings_are_rejected_without_overwrite(self):
        for original in ("{not json", '{"version": 99, "rules": []}'):
            with self.subTest(original=original):
                self.path.write_text(original, encoding="utf-8")
                with self.assertRaises(SettingsError):
                    self.store.load_rules()
                self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_duplicate_rules_are_rejected(self):
        self.path.write_text(
            '{"version": 1, "rules": ['
            '{"executable": "discord.exe", "volume": 20, "enabled": true},'
            '{"executable": "Discord.EXE", "volume": 60, "enabled": true}]}',
            encoding="utf-8",
        )
        with self.assertRaises(SettingsError):
            self.store.load_rules()

    def test_update_replaces_file_without_leaving_a_temporary_file(self):
        self.store.save_rules([AppRule("Discord.exe", 20)])
        self.store.save_rules([AppRule("Discord.exe", 55)])
        self.assertEqual(self.store.load_rules()[0].volume, 55)
        self.assertEqual(list(self.path.parent.glob("settings-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
