"""Regression checks for process search, selection, and list scrollbars."""

import tkinter as tk
import unittest

from app import VolumeManagerApp
from app_volume_manager.volume_service import AudioSession


class ProcessSearchTests(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            AudioSession(
                "Discord.exe", "discord-session", lambda _value: None,
                process_id=4242, current_volume=35, process_signature="discord.exe|main",
                process_role="Main process", session_name="Voice Chat", device_name="Speakers",
            ),
            AudioSession(
                "Spotify.exe", "spotify-session", lambda _value: None,
                process_id=8123, current_volume=62, process_signature="spotify.exe|main",
                process_role="Main process", session_name="Music", device_name="Headphones",
            ),
        ]
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available in this environment: {exc}")
        self.addCleanup(self.root.destroy)
        self.root.geometry("900x460")
        self.app = VolumeManagerApp.__new__(VolumeManagerApp)
        self.app.root = self.root
        self.app.last_sessions = self.sessions
        self.app.rules = []
        self.app.checked_rows = set()
        self.app._row_info = {}
        self.app._all_row_info = {}
        self.app.temporary_process_targets = {}
        self.app._build_ui()
        self.root.update_idletasks()
        self.root.update()

    def test_search_matches_executable_pid_and_device_case_insensitively(self):
        self.app.search_var.set("DISCORD 4242")
        self.root.update_idletasks()
        visible = self.app.table.get_children()
        self.assertEqual(len(visible), 1)
        self.assertEqual(self.app.table.item(visible[0], "values")[1], "Discord.exe")

        self.app.search_var.set("headphones")
        self.root.update_idletasks()
        visible = self.app.table.get_children()
        self.assertEqual(len(visible), 1)
        self.assertEqual(self.app.table.item(visible[0], "values")[1], "Spotify.exe")

    def test_selected_process_stays_selected_while_hidden_by_search(self):
        discord_id = next(
            row_id for row_id, row in self.app._all_row_info.items()
            if row.executable == "Discord.exe"
        )
        self.app.checked_rows.add(discord_id)
        self.app._sync_volume_scale_enabled()
        self.app.search_var.set("headphones")
        self.root.update_idletasks()
        self.assertEqual(len(self.app.table.get_children()), 1)
        self.assertIn(discord_id, self.app.checked_rows)
        self.assertEqual([row.executable for row in self.app._selected_rows()], ["Discord.exe"])
        self.assertTrue(self.app.volume_scale.instate(["!disabled"]))
        self.assertIn("1 selected", self.app.search_summary_var.get())

        self.app.search_var.set("")
        self.root.update_idletasks()
        self.assertEqual(len(self.app.table.get_children()), 2)

    def test_custom_color_is_used_for_both_scrollbars(self):
        self.app._set_slider_thumb_color("#AB12CD")
        for orientation in ("Vertical", "Horizontal"):
            self.assertEqual(
                self.app.style.lookup(f"App.{orientation}.TScrollbar", "background"), "#AB12CD"
            )

    def test_vertical_scrollbar_appears_only_when_the_list_overflows(self):
        self.assertFalse(self.app.vertical_scrollbar.winfo_ismapped())
        self.app.last_sessions = [
            AudioSession(
                f"app{index}.exe", f"session-{index}", lambda _value: None,
                process_id=1000 + index, current_volume=40,
                process_signature=f"app{index}.exe|main", process_role="Main process",
            )
            for index in range(10)
        ]
        self.app._refresh_table()
        self.root.update_idletasks()
        self.root.update()
        self.assertTrue(self.app.vertical_scrollbar.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
