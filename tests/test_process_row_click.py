"""Check process-row selection using the same callback as the UI."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app import VolumeManagerApp


class ProcessRowClickTests(unittest.TestCase):
    def setUp(self):
        self.app = VolumeManagerApp.__new__(VolumeManagerApp)
        self.app.table = Mock()
        self.app.table.identify_region.return_value = "cell"
        self.app.table.identify_row.return_value = "discord-row"
        self.app.table.get_children.return_value = ("discord-row",)
        self.app._row_info = {"discord-row": object()}
        self.app.checked_rows = set()
        self.app._refresh_table = Mock()

    def test_clicking_a_row_toggles_selection_and_keeps_highlight(self):
        event = SimpleNamespace(x=320, y=12)
        self.assertEqual(self.app._on_table_click(event), "break")
        self.assertEqual(self.app.checked_rows, {"discord-row"})
        self.app.table.selection_set.assert_called_once_with("discord-row")
        self.app.table.focus.assert_called_once_with("discord-row")
        self.app._on_table_click(event)
        self.assertEqual(self.app.checked_rows, set())

    def test_click_outside_a_data_cell_is_not_intercepted(self):
        self.app.table.identify_region.return_value = "heading"
        self.assertIsNone(self.app._on_table_click(SimpleNamespace(x=320, y=0)))
        self.assertEqual(self.app.checked_rows, set())
        self.app._refresh_table.assert_not_called()


if __name__ == "__main__":
    unittest.main()
