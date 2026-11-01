"""Check process-row selection using the same callback as the UI."""

import unittest
from types import SimpleNamespace

from app_volume_manager.volume_service import AudioSession
from tests.support import open_window


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
        self.row_id = next(iter(self.app._row_info))
        x, y, _width, _height = self.app.table.bbox(self.row_id, "pid")
        self.cell = SimpleNamespace(x=x + 2, y=y + 2)

    def test_clicking_a_row_toggles_selection_and_keeps_highlight(self):
        self.assertEqual(self.app._on_table_click(self.cell), "break")
        self.assertEqual(self.app.checked_rows, {self.row_id})
        self.assertEqual(self.app.table.selection(), (self.row_id,))
        self.assertEqual(self.app.table.focus(), self.row_id)
        self.app._on_table_click(self.cell)
        self.assertEqual(self.app.checked_rows, set())

    def test_click_outside_a_data_cell_is_not_intercepted(self):
        heading = SimpleNamespace(x=self.cell.x, y=2)
        self.assertIsNone(self.app._on_table_click(heading))
        self.assertEqual(self.app.checked_rows, set())
        self.assertEqual(self.app.table.item(self.row_id, "values")[0], "☐")


if __name__ == "__main__":
    unittest.main()
