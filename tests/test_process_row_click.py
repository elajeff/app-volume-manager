"""Check process-row selection using the same callback as the UI."""

import unittest

from app_volume_manager.volume_service import AudioSession
from tests.support import click_row, open_window


class ProcessRowClickTests(unittest.TestCase):
    def setUp(self):
        self.app = open_window(self, sessions=[
            AudioSession(
                "Discord.exe", "discord-session", lambda _value: None,
                process_id=4242, current_volume=35, process_signature="discord.exe|main",
                process_role="Main process",
            )
        ])
        self.app.root.update()
        self.row_id = self.app.table.get_children()[0]

    def test_clicking_a_row_toggles_selection_and_keeps_highlight(self):
        click_row(self.app, self.row_id, "pid")
        self.assertEqual(self.app.checked_rows, {self.row_id})
        self.assertEqual(self.app.table.selection(), (self.row_id,))
        self.assertEqual(self.app.table.focus(), self.row_id)
        click_row(self.app, self.row_id, "pid")
        self.assertEqual(self.app.checked_rows, set())

    def test_click_outside_a_data_cell_is_not_intercepted(self):
        x, _y, _width, _height = self.app.table.bbox(self.row_id, "pid")
        self.app.table.event_generate("<Button-1>", x=x + 2, y=2)
        self.assertEqual(self.app.checked_rows, set())
        self.assertEqual(self.app.table.item(self.row_id, "values")[0], "☐")


if __name__ == "__main__":
    unittest.main()
