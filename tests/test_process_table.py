import tkinter as tk
import unittest

from app_volume_manager.ui.process_table import HEADINGS, ProcessTable


class ProcessTableTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available in this environment: {exc}")
        self.addCleanup(self.root.destroy)
        self.table = ProcessTable(self.root, lambda _event: None)
        self.table.frame.pack(fill="both", expand=True)

    def resize(self, width):
        self.root.geometry(f"{width}x300")
        self.root.update()
        self.table.fit_columns()
        self.root.update()

    def total_width(self):
        return sum(int(self.table.tree.column(name, "width")) for name, _title in HEADINGS)

    def test_wide_window_fills_the_table_without_a_horizontal_scrollbar(self):
        self.resize(1100)
        self.assertEqual(self.total_width(), self.table.tree.winfo_width() - 4)
        self.assertFalse(self.table.horizontal_scrollbar.winfo_ismapped())

    def test_narrow_window_keeps_minimum_widths_and_shows_the_scrollbar(self):
        self.resize(500)
        self.assertEqual(self.total_width(), 728)
        self.assertTrue(self.table.horizontal_scrollbar.winfo_ismapped())

    def test_rebuild_keeps_the_selection_only_for_selectable_rows(self):
        self.table.show({"a": ("a",) * 8, "b": ("b",) * 8}, selectable={"a", "b"})
        self.table.tree.selection_set("b")
        self.table.show({"b": ("b",) * 8}, selectable={"b"})
        self.assertEqual(self.table.tree.selection(), ("b",))
        self.table.show({"c": ("c",) * 8}, selectable=set())
        self.assertEqual(self.table.tree.selection(), ())


if __name__ == "__main__":
    unittest.main()
