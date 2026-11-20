"""Regression checks for the process list: rows, search, selection, refresh and scrollbars."""

import unittest
from tkinter import ttk
from unittest.mock import patch

from app_volume_manager.volume_service import AudioSession
from tests.support import click_row, descendants, open_window


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
        self.app = open_window(self, sessions=self.sessions)
        self.root = self.app.root
        self.root.geometry("900x460")
        self.root.update_idletasks()
        self.root.update()

    def set_sessions(self, sessions):
        self.app.backend.sessions = list(sessions)
        self.app.refresh_list()

    def test_active_process_row_shows_its_details(self):
        values = self.app.table.item(self.row_id("Discord.exe"), "values")
        self.assertEqual(values[2], "4242")
        self.assertEqual(values[3], "1")  # one Windows audio session for this process
        self.assertEqual(values[7], "Not configured")
        headings = [self.app.table.heading(column, "text") for column in self.app.table["columns"]]
        self.assertIn("Rule status", headings)
        self.assertIn("Sessions", headings)
        self.assertNotIn("Process role", headings)

    def test_refresh_button_lists_devices_again_and_shows_new_sessions(self):
        button = next(
            widget for widget in descendants(self.root)
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Refresh list"
        )
        self.app.backend.sessions = [AudioSession("Steam.exe", "steam-session", lambda _value: None, process_id=77)]
        button.invoke()
        self.assertEqual(self.app.backend.invalidated, 1)
        self.assertEqual([self.app.table.item(row, "values")[1] for row in self.app.table.get_children()],
                         ["Steam.exe"])
        self.assertIn("1 process", self.app.status_var.get())

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
        discord_id = self.row_id("Discord.exe")
        click_row(self.app, discord_id)
        self.app.search_var.set("headphones")
        self.root.update_idletasks()
        self.assertEqual(len(self.app.table.get_children()), 1)
        self.assertIn(discord_id, self.app.checked_rows)
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
        self.assertFalse(self.app.process_table.vertical_scrollbar.winfo_ismapped())
        self.set_sessions(
            AudioSession(
                f"app{index}.exe", f"session-{index}", lambda _value: None,
                process_id=1000 + index, current_volume=40,
                process_signature=f"app{index}.exe|main", process_role="Main process",
            )
            for index in range(10)
        )
        self.root.update_idletasks()
        self.root.update()
        self.assertTrue(self.app.process_table.vertical_scrollbar.winfo_ismapped())

    def row_id(self, executable):
        return next(row_id for row_id in self.app.table.get_children()
                    if self.app.table.item(row_id, "values")[1] == executable)

    def test_unchanged_refresh_does_not_touch_the_table(self):
        with patch.object(self.app.table, "item") as item, patch.object(self.app.table, "delete") as delete:
            self.app.refresh_list()
        item.assert_not_called()
        delete.assert_not_called()

    def test_volume_change_updates_only_that_row_and_keeps_the_selection(self):
        discord_id = self.row_id("Discord.exe")
        self.app.table.selection_set(discord_id)
        before = self.app.table.get_children()
        self.sessions[0].current_volume = 80
        self.app.refresh_list()
        self.assertEqual(self.app.table.get_children(), before)
        self.assertEqual(self.app.table.selection(), (discord_id,))
        self.assertEqual(self.app.table.item(discord_id, "values")[5], "80%")

    def test_clicking_a_row_flips_its_checkbox_in_place_and_highlights_it(self):
        discord_id = self.row_id("Discord.exe")
        with patch.object(self.app.table, "delete") as delete:
            click_row(self.app, discord_id)
        delete.assert_not_called()
        self.assertEqual(self.app.table.item(discord_id, "values")[0], "\u2611")
        self.assertEqual(self.app.table.selection(), (discord_id,))
        self.assertEqual(self.app.table.focus(), discord_id)
        self.assertIn("1 selected", self.app.search_summary_var.get())
        click_row(self.app, discord_id)
        self.assertEqual(self.app.table.item(discord_id, "values")[0], "\u2610")

    def test_clicking_the_heading_does_not_check_a_row(self):
        discord_id = self.row_id("Discord.exe")
        x, _y, _width, _height = self.app.table.bbox(discord_id, "pid")
        self.app.table.event_generate("<Button-1>", x=x + 2, y=2)
        self.assertEqual(self.app.checked_rows, set())
        self.assertEqual(self.app.table.item(discord_id, "values")[0], "☐")

    def test_rows_appearing_or_leaving_rebuild_the_table_and_keep_a_surviving_selection(self):
        spotify_id = self.row_id("Spotify.exe")
        self.app.table.selection_set(spotify_id)
        self.set_sessions(self.sessions[1:])
        self.assertEqual(self.app.table.get_children(), (spotify_id,))
        self.assertEqual(self.app.table.selection(), (spotify_id,))
        self.set_sessions([])
        self.assertEqual(self.app.table.get_children(), ("no-audio-sessions",))


if __name__ == "__main__":
    unittest.main()
