import tkinter as tk
import unittest
from tkinter import ttk
from unittest.mock import Mock, patch

from app_volume_manager.rules import AppRule
from app_volume_manager.ui.rule_dialog import show_rule_dialog


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class RuleDialogTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available in this environment: {exc}")
        self.addCleanup(self.root.destroy)

    def open_dialog(self, save_rule):
        # wait_window would block the test until the dialog closes.
        with patch.object(self.root, "wait_window"):
            show_rule_dialog(self.root, ["Discord.exe", "Spotify.exe"], 35, save_rule)
        dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel))
        entry = next(
            widget for widget in descendants(dialog)
            if isinstance(widget, ttk.Entry) and not isinstance(widget, ttk.Combobox)
        )
        save_button = next(
            widget for widget in descendants(dialog)
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Save rule"
        )
        return dialog, entry, save_button

    def test_save_passes_a_validated_rule_and_closes(self):
        save_rule = Mock()
        dialog, entry, save_button = self.open_dialog(save_rule)
        entry.insert(0, r"C:\Apps\discord")
        save_button.invoke()
        save_rule.assert_called_once_with(AppRule("discord.exe", 35, True))
        self.assertFalse(dialog.winfo_exists())

    def test_rejected_rule_shows_the_error_and_keeps_the_dialog_open(self):
        save_rule = Mock(side_effect=ValueError("not allowed"))
        dialog, entry, save_button = self.open_dialog(save_rule)
        entry.insert(0, "discord")
        with patch("app_volume_manager.ui.rule_dialog.messagebox.showerror") as error:
            save_button.invoke()
        self.assertEqual(error.call_args.args[1], "not allowed")
        self.assertTrue(dialog.winfo_exists())

    def test_empty_name_is_reported_without_saving(self):
        save_rule = Mock()
        dialog, _entry, save_button = self.open_dialog(save_rule)
        with patch("app_volume_manager.ui.rule_dialog.messagebox.showerror") as error:
            save_button.invoke()
        error.assert_called_once()
        save_rule.assert_not_called()
        self.assertTrue(dialog.winfo_exists())


if __name__ == "__main__":
    unittest.main()
