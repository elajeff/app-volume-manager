import unittest
from types import SimpleNamespace

from app_volume_manager.ui.volume_scale import allow_scale_thumb_click
from app_volume_manager.volume_service import AudioSession
from tests.support import open_window


class FakeScale:
    def __init__(self, element: str) -> None:
        self.element = element

    def identify(self, _x: int, _y: int) -> str:
        return self.element


class ScaleInteractionTests(unittest.TestCase):
    def event_for(self, element: str):
        return SimpleNamespace(widget=FakeScale(element), x=12, y=6)

    def test_click_on_slider_thumb_keeps_native_drag_behavior(self):
        self.assertIsNone(allow_scale_thumb_click(self.event_for("Horizontal.Scale.slider")))

    def test_non_thumb_clicks_do_not_jump_volume(self):
        for element in ("trough", ""):
            with self.subTest(element=element):
                self.assertEqual(allow_scale_thumb_click(self.event_for(element)), "break")

    def test_volume_scale_is_disabled_until_a_process_is_checked(self):
        app = open_window(self, sessions=[
            AudioSession("Discord.exe", "session", lambda _value: None, process_id=4242, current_volume=35),
        ])
        row_id = next(iter(app._all_row_info))
        self.assertTrue(app.volume_scale.instate(["disabled"]))
        self.assertEqual(app.target_volume_label.get(), "Select a process to change volume")

        app.checked_rows.add(row_id)
        app._sync_volume_scale_enabled()
        self.assertTrue(app.volume_scale.instate(["!disabled"]))
        self.assertEqual(app.target_volume_label.get(), "Volume for selected: 50%")

        app.checked_rows.clear()
        app._sync_volume_scale_enabled()
        self.assertTrue(app.volume_scale.instate(["disabled"]))


if __name__ == "__main__":
    unittest.main()
