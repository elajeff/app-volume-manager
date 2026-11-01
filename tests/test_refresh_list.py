import unittest
from tkinter import ttk

from app_volume_manager.volume_service import AudioSession
from tests.support import open_window


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class RefreshListTests(unittest.TestCase):
    def test_refresh_button_lists_devices_again_and_shows_new_sessions(self):
        app = open_window(self)
        self.assertEqual(app.table.get_children(), ("no-audio-sessions",))
        button = next(
            widget for widget in descendants(app.root)
            if isinstance(widget, ttk.Button) and widget.cget("text") == "Refresh list"
        )

        app.backend.sessions = [AudioSession("Spotify.exe", "session", lambda _value: None, process_id=77)]
        button.invoke()

        self.assertEqual(app.backend.invalidated, 1)
        rows = app.table.get_children()
        self.assertEqual(len(rows), 1)
        self.assertEqual(app.table.item(rows[0], "values")[1], "Spotify.exe")
        self.assertIn("1 process", app.status_var.get())

        app.backend.sessions = []
        button.invoke()
        self.assertEqual(app.table.get_children(), ("no-audio-sessions",))
        self.assertEqual(app.backend.invalidated, 2)


if __name__ == "__main__":
    unittest.main()
