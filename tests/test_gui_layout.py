"""Regression tests for the visible process table in the Tkinter window."""

import unittest

from app_volume_manager.volume_service import AudioSession
from tests.support import open_window


class ProcessTableLayoutTests(unittest.TestCase):
    def test_active_audio_process_is_inserted_into_visible_table(self):
        app = open_window(self, sessions=[
            AudioSession(
                executable="Discord.exe",
                session_id="device-one|session-one",
                set_volume=lambda _value: None,
                process_id=4242,
                current_volume=35,
                process_signature="discord.exe|main",
                process_role="Main process",
                session_name="Voice Chat",
                device_name="Speakers",
            )
        ])
        app.root.update_idletasks()

        self.assertIs(app.table.master, app.process_table.frame)
        self.assertEqual(app.table.winfo_manager(), "grid")
        self.assertEqual(app.process_table.frame.winfo_manager(), "grid")
        rows = app.table.get_children()
        self.assertEqual(len(rows), 1)
        values = app.table.item(rows[0], "values")
        self.assertEqual(values[1], "Discord.exe")
        self.assertEqual(values[2], "4242")
        self.assertEqual(values[3], "1")  # one Windows audio session for this process
        self.assertEqual(values[7], "Not configured")
        headings = [app.table.heading(column, "text") for column in app.table["columns"]]
        self.assertIn("Rule status", headings)
        self.assertIn("Sessions", headings)
        self.assertNotIn("Process role", headings)
        self.assertEqual(int(app.table.cget("height")), 7)

        # Automatic table refreshes should not discard the user's blue row highlight.
        app.table.selection_set(rows[0])
        app._refresh_table()
        self.assertEqual(app.table.selection(), (rows[0],))


if __name__ == "__main__":
    unittest.main()
