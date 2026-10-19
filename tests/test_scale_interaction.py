import unittest
from types import SimpleNamespace

from app import VolumeManagerApp, allow_scale_thumb_click


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
        class FakeVolumeScale:
            def __init__(self):
                self.last_state = None

            def state(self, value):
                self.last_state = value

        app = VolumeManagerApp.__new__(VolumeManagerApp)
        app.volume_scale = FakeVolumeScale()
        app.checked_rows = set()
        app._row_info = {"discord": object()}

        app._sync_volume_scale_enabled()
        self.assertEqual(app.volume_scale.last_state, ["disabled"])

        app.checked_rows.add("discord")
        app._sync_volume_scale_enabled()
        self.assertEqual(app.volume_scale.last_state, ["!disabled"])

        app.checked_rows.clear()
        app._sync_volume_scale_enabled()
        self.assertEqual(app.volume_scale.last_state, ["disabled"])


if __name__ == "__main__":
    unittest.main()
