"""GUI regression checks for locking a picked color until the pointer re-enters."""

import tkinter as tk
import unittest
from tkinter import ttk

from app import VolumeManagerApp


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class SliderColorPickerInteractionTests(unittest.TestCase):
    def test_palette_and_hue_clicks_stay_fixed_until_pointer_leaves(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available in this environment: {exc}")

        app = VolumeManagerApp.__new__(VolumeManagerApp)
        app.root = root
        app.slider_thumb_color = "#1677FF"
        app.status_var = tk.StringVar(master=root)
        applied_colors = []

        def set_color(color):
            app.slider_thumb_color = color
            applied_colors.append(color)

        app._set_slider_thumb_color = set_color
        app.preference_store = object()
        callback_errors = []

        def exercise_picker():
            try:
                dialogs = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
                self.assertEqual(len(dialogs), 1)
                dialog = dialogs[0]
                canvases = [child for child in descendants(dialog) if isinstance(child, tk.Canvas)]
                palette = next(canvas for canvas in canvases if int(canvas.cget("width")) == 230)
                hue = next(canvas for canvas in canvases if int(canvas.cget("width")) == 18)

                # Click the palette, then move within it toward the edge as a user
                # might while heading for Save. The clicked color must stay fixed.
                palette.event_generate("<Motion>", x=90, y=70, when="now")
                palette.event_generate("<Button-1>", x=90, y=70, when="now")
                selected_palette_color = app.slider_thumb_color
                palette.event_generate("<Motion>", x=220, y=0, when="now")
                self.assertEqual(app.slider_thumb_color, selected_palette_color)
                palette.event_generate("<Leave>", when="now")
                palette.event_generate("<Motion>", x=220, y=0, when="now")
                self.assertNotEqual(app.slider_thumb_color, selected_palette_color)

                # The hue marker/color similarly stays fixed after a click, then
                # hover selection works again after the pointer leaves and returns.
                hue.event_generate("<Motion>", x=8, y=35, when="now")
                hue.event_generate("<Button-1>", x=8, y=50, when="now")
                selected_hue_color = app.slider_thumb_color
                hue.event_generate("<Motion>", x=8, y=130, when="now")
                self.assertEqual(app.slider_thumb_color, selected_hue_color)
                hue.event_generate("<Leave>", when="now")
                hue.event_generate("<Motion>", x=8, y=130, when="now")
                self.assertNotEqual(app.slider_thumb_color, selected_hue_color)

                cancel_button = next(
                    child for child in descendants(dialog)
                    if isinstance(child, ttk.Button) and child.cget("text") == "Cancel"
                )
                cancel_button.invoke()
            except BaseException as exc:
                callback_errors.append(exc)
                for child in root.winfo_children():
                    if isinstance(child, tk.Toplevel):
                        child.destroy()

        try:
            root.after(150, exercise_picker)
            app.edit_slider_thumb_color()
            if callback_errors:
                raise callback_errors[0]
        finally:
            root.destroy()

    def test_reset_to_default_previews_and_saves_blue(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is not available in this environment: {exc}")

        app = VolumeManagerApp.__new__(VolumeManagerApp)
        app.root = root
        app.slider_thumb_color = "#AB12CD"
        app.status_var = tk.StringVar(master=root)
        saved_colors = []

        def set_color(color):
            app.slider_thumb_color = color

        class FakePreferenceStore:
            def save_slider_thumb_color(self, color):
                saved_colors.append(color)

        app._set_slider_thumb_color = set_color
        app.preference_store = FakePreferenceStore()
        callback_errors = []

        def reset_and_save():
            try:
                dialog = next(
                    child for child in root.winfo_children()
                    if isinstance(child, tk.Toplevel)
                )
                buttons = [
                    child for child in descendants(dialog)
                    if isinstance(child, ttk.Button)
                ]
                reset_button = next(button for button in buttons if button.cget("text") == "Reset to default")
                reset_button.invoke()
                self.assertEqual(app.slider_thumb_color, "#1677FF")
                save_button = next(button for button in buttons if button.cget("text") == "Save color")
                save_button.invoke()
            except BaseException as exc:
                callback_errors.append(exc)
                for child in root.winfo_children():
                    if isinstance(child, tk.Toplevel):
                        child.destroy()

        try:
            root.after(150, reset_and_save)
            app.edit_slider_thumb_color()
            if callback_errors:
                raise callback_errors[0]
            self.assertEqual(saved_colors, ["#1677FF"])
            self.assertIn("saved", app.status_var.get().casefold())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
