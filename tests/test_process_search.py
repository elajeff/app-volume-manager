"""Regression checks for process search, selection, and list scrollbars."""

import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import DEFAULT_SLIDER_THUMB_COLOR, VolumeManagerApp
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
        self.app._shown_rows = {}
        self.app.temporary_process_targets = {}
        self.app.slider_thumb_color = DEFAULT_SLIDER_THUMB_COLOR
        self.app._apply_theme("light")
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


    def discord_row_id(self):
        return next(row_id for row_id, row in self.app._all_row_info.items() if row.executable == "Discord.exe")

    def test_unchanged_refresh_does_not_touch_the_table(self):
        with patch.object(self.app.table, "item") as item, patch.object(self.app.table, "delete") as delete:
            self.app._refresh_table()
        item.assert_not_called()
        delete.assert_not_called()

    def test_volume_change_updates_only_that_row_and_keeps_the_selection(self):
        discord_id = self.discord_row_id()
        self.app.table.selection_set(discord_id)
        before = self.app.table.get_children()
        self.sessions[0].current_volume = 80
        self.app._refresh_table()
        self.assertEqual(self.app.table.get_children(), before)
        self.assertEqual(self.app.table.selection(), (discord_id,))
        self.assertEqual(self.app.table.item(discord_id, "values")[5], "80%")

    def test_clicking_a_row_flips_its_checkbox_in_place_and_highlights_it(self):
        discord_id = self.discord_row_id()
        x, y, _width, _height = self.app.table.bbox(discord_id, "application")
        event = SimpleNamespace(x=x + 2, y=y + 2)
        with patch.object(self.app.table, "delete") as delete:
            self.assertEqual(self.app._on_table_click(event), "break")
        delete.assert_not_called()
        self.assertEqual(self.app.table.item(discord_id, "values")[0], "\u2611")
        self.assertEqual(self.app.table.selection(), (discord_id,))
        self.assertIn("1 selected", self.app.search_summary_var.get())
        self.app._on_table_click(event)
        self.assertEqual(self.app.table.item(discord_id, "values")[0], "\u2610")

    def test_rows_appearing_or_leaving_rebuild_the_table_and_keep_a_surviving_selection(self):
        spotify_id = next(row_id for row_id, row in self.app._all_row_info.items() if row.executable == "Spotify.exe")
        self.app.table.selection_set(spotify_id)
        self.app.last_sessions = self.sessions[1:]
        self.app._refresh_table()
        self.assertEqual(self.app.table.get_children(), (spotify_id,))
        self.assertEqual(self.app.table.selection(), (spotify_id,))
        self.app.last_sessions = []
        self.app._refresh_table()
        self.assertEqual(self.app.table.get_children(), ("no-audio-sessions",))


if __name__ == "__main__":
    unittest.main()
