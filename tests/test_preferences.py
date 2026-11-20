import json
import tempfile
import unittest
from pathlib import Path

from app_volume_manager.settings import PreferenceStore, SettingsError


class PreferenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "preferences.json"
        self.store = PreferenceStore(self.path)

    def test_defaults_and_theme_changes_survive_reload(self):
        self.assertEqual(self.store.load_preferences()[0], "light")
        self.store.save_theme("dark")
        reloaded = PreferenceStore(self.path)
        self.assertEqual(reloaded.load_preferences(), ("dark", "#1677FF"))
        reloaded.save_theme("light")
        self.assertEqual(reloaded.load_preferences()[0], "light")

    def test_custom_slider_color_survives_theme_changes_and_older_settings(self):
        self.path.write_text(json.dumps({"version": 1, "theme": "dark"}), encoding="utf-8")
        self.assertEqual(self.store.load_preferences(), ("dark", "#1677FF"))
        self.store.save_slider_thumb_color("#ab12cd")
        self.store.save_theme("light")
        self.assertEqual(PreferenceStore(self.path).load_preferences(), ("light", "#AB12CD"))

    def test_invalid_preferences_are_rejected(self):
        for operation, value in (
            (self.store.save_slider_thumb_color, "blue"),
            (self.store.save_theme, "midnight"),
        ):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                operation(value)

    def test_malformed_preferences_are_reported_without_overwriting(self):
        original = "{broken"
        self.path.write_text(original, encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.store.load_preferences()[0]
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
