"""Modal Tk color editor for the volume slider."""

import colorsys
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from app_volume_manager.color_utils import (
    hex_to_rgb,
    hsv_to_hex,
    normalize_hex_color,
    rgb_to_hex,
)
from app_volume_manager.settings import PreferenceStore, SettingsError
from app_volume_manager.ui import APP_NAME


class SliderColorDialog:
    """A live color picker; Save persists the preview and Cancel reverts it."""

    PALETTE_WIDTH = 230
    PALETTE_HEIGHT = 160
    HUE_WIDTH = 18

    def __init__(
        self,
        parent: tk.Misc,
        original_color: str,
        preference_store: PreferenceStore,
        apply_color: Callable[[str], None],
        status_var: tk.StringVar,
    ) -> None:
        self.parent = parent
        self.original_color = normalize_hex_color(original_color)
        self.current_color = self.original_color
        self.preference_store = preference_store
        self.apply_color = apply_color
        self.status_var = status_var
        self.active_editor: str | None = None
        current_rgb = hex_to_rgb(self.current_color)
        self.hsv = list(colorsys.rgb_to_hsv(*(channel / 255 for channel in current_rgb)))
        self.rendered_hue = -1.0
        # Hover previews are convenient, but once a user clicks a point, keep
        # that choice fixed while they move the pointer away to Save. Leaving
        # and re-entering the same canvas enables hover previews again.
        self.palette_locked = False
        self.hue_locked = False
        self.saturations = [x / (self.PALETTE_WIDTH - 1) for x in range(self.PALETTE_WIDTH)]

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Customize slider color")
        self.dialog.transient(parent)
        self.dialog.resizable(False, False)
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)

        frame = ttk.Frame(self.dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=(
                "Hover to preview. Click a point to keep its color while moving away; "
                "leave and re-enter to preview again. Drag to adjust continuously."
            ),
            wraplength=430,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.palette_canvas = tk.Canvas(
            frame, width=self.PALETTE_WIDTH, height=self.PALETTE_HEIGHT,
            highlightthickness=1, highlightbackground="#7b8492", bd=0,
        )
        self.palette_canvas.grid(row=1, column=0, sticky="n")
        self.hue_canvas = tk.Canvas(
            frame, width=self.HUE_WIDTH, height=self.PALETTE_HEIGHT,
            highlightthickness=1, highlightbackground="#7b8492", bd=0,
        )
        self.hue_canvas.grid(row=1, column=1, sticky="n", padx=(7, 14))

        fields_frame = ttk.Frame(frame)
        fields_frame.grid(row=1, column=2, sticky="n")
        ttk.Label(fields_frame, text="RGB values").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.rgb_vars = [tk.StringVar(value=str(channel)) for channel in current_rgb]
        for row_index, (label, variable) in enumerate(
            zip(("Red", "Green", "Blue"), self.rgb_vars, strict=True), start=1
        ):
            ttk.Label(fields_frame, text=label).grid(row=row_index, column=0, sticky="w", padx=(0, 8))
            entry = ttk.Entry(fields_frame, textvariable=variable, width=6, justify="right")
            entry.grid(row=row_index, column=1, sticky="ew", pady=2)
            self._bind_entry(entry, self.on_rgb_edit)

        ttk.Label(fields_frame, text="HEX value").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(9, 2)
        )
        self.hex_var = tk.StringVar(value=self.current_color)
        hex_entry = ttk.Entry(fields_frame, textvariable=self.hex_var, width=12)
        hex_entry.grid(row=5, column=0, columnspan=2, sticky="ew")
        self._bind_entry(hex_entry, self.on_hex_edit)
        self.swatch = tk.Label(
            fields_frame, text="Preview", bg=self.current_color, fg="white",
            relief="solid", bd=1, padx=12, pady=5,
        )
        self.swatch.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.palette_photo = tk.PhotoImage(master=self.dialog, width=self.PALETTE_WIDTH, height=self.PALETTE_HEIGHT)
        self.hue_photo = tk.PhotoImage(master=self.dialog, width=self.HUE_WIDTH, height=self.PALETTE_HEIGHT)
        self.palette_canvas.create_image(0, 0, image=self.palette_photo, anchor="nw")
        self.hue_canvas.create_image(0, 0, image=self.hue_photo, anchor="nw")

        self.palette_canvas.bind("<Motion>", self.palette_motion)
        self.palette_canvas.bind("<Button-1>", self.palette_click)
        # Dragging changes the selection, even after a click.
        self.palette_canvas.bind("<B1-Motion>", self.set_palette_point)
        self.palette_canvas.bind("<Leave>", self.palette_leave)
        self.hue_canvas.bind("<Motion>", self.hue_motion)
        self.hue_canvas.bind("<Button-1>", self.hue_click)
        self.hue_canvas.bind("<B1-Motion>", self.set_hue_point)
        self.hue_canvas.bind("<Leave>", self.hue_leave)
        self.draw_palette(self.hsv[0])
        self.draw_hue_strip()
        self.draw_palette_marker()
        self.draw_hue_marker(self.hsv[0])

        ttk.Label(
            frame,
            text="RGB accepts whole numbers from 0 to 255. HEX accepts #RRGGBB.",
            foreground="#687386",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(9, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(
            buttons, text="Reset to default", command=self.reset_to_default
        ).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Save color", command=self.save).pack(side="right")
        self.dialog.bind("<Escape>", lambda _event: self.cancel())
        self.dialog.bind("<Return>", lambda _event: self.save())

    def show(self) -> None:
        """Block until the dialog is closed."""
        self.dialog.grab_set()
        self.parent.wait_window(self.dialog)

    @staticmethod
    def _bind_entry(entry: ttk.Entry, on_edit: Callable) -> None:
        entry.bind("<FocusIn>", lambda event: event.widget.selection_range(0, "end"))
        entry.bind("<KeyRelease>", on_edit)
        entry.bind("<Return>", on_edit)
        entry.bind("<FocusOut>", on_edit)

    def draw_palette(self, hue: float) -> None:
        # This runs on every hue change, so it skips hsv_to_hex()'s validation
        # and hands Tk the whole image in one call.
        hsv_to_rgb = colorsys.hsv_to_rgb
        rows = []
        for y in range(self.PALETTE_HEIGHT):
            value = 1.0 - y / (self.PALETTE_HEIGHT - 1)
            cells = []
            for saturation in self.saturations:
                red, green, blue = hsv_to_rgb(hue, saturation, value)
                cells.append(f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}")
            rows.append("{" + " ".join(cells) + "}")
        self.palette_photo.put(" ".join(rows))
        self.rendered_hue = hue

    def draw_hue_strip(self) -> None:
        for y in range(self.PALETTE_HEIGHT):
            hue_color = hsv_to_hex(y / (self.PALETTE_HEIGHT - 1), 1.0, 1.0)
            self.hue_photo.put(
                "{" + " ".join([hue_color] * self.HUE_WIDTH) + "}", to=(0, y)
            )

    def draw_palette_marker(self) -> None:
        """Show the current saturation/value point on the large color square."""
        canvas = self.palette_canvas
        canvas.delete("palette-marker")
        x = round(self.hsv[1] * (self.PALETTE_WIDTH - 1))
        y = round((1.0 - self.hsv[2]) * (self.PALETTE_HEIGHT - 1))
        # A dark outline plus a short white center stays visible on most colors.
        canvas.create_line(x - 7, y, x + 7, y, fill="#101010", width=3, tags="palette-marker")
        canvas.create_line(x, y - 7, x, y + 7, fill="#101010", width=3, tags="palette-marker")
        canvas.create_line(x - 6, y, x + 6, y, fill="#FFFFFF", width=1, tags="palette-marker")
        canvas.create_line(x, y - 6, x, y + 6, fill="#FFFFFF", width=1, tags="palette-marker")

    def draw_hue_marker(self, hue: float) -> None:
        """Keep a high-contrast line at the currently selected hue."""
        canvas = self.hue_canvas
        canvas.delete("hue-marker")
        y = round((hue % 1.0) * (self.PALETTE_HEIGHT - 1))
        if y > 0:
            canvas.create_line(0, y - 1, self.HUE_WIDTH, y - 1, fill="#101010", width=1, tags="hue-marker")
        canvas.create_line(0, y, self.HUE_WIDTH, y, fill="#FFFFFF", width=2, tags="hue-marker")
        if y < self.PALETTE_HEIGHT - 1:
            canvas.create_line(0, y + 1, self.HUE_WIDTH, y + 1, fill="#101010", width=1, tags="hue-marker")

    def update_preview(self, color: str, fields: str = "all", recalculate_hsv: bool = False) -> None:
        self.current_color = normalize_hex_color(color)
        self.apply_color(self.current_color)
        red, green, blue = hex_to_rgb(self.current_color)
        if recalculate_hsv:
            self.hsv[:] = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        # Editing RGB/HEX changes the hue too, so keep both color surfaces
        # and their position indicators synchronized with the live preview.
        if abs(self.hsv[0] - self.rendered_hue) > 0.0001:
            self.draw_palette(self.hsv[0])
        self.draw_palette_marker()
        self.draw_hue_marker(self.hsv[0])
        brightness = (red * 299 + green * 587 + blue * 114) / 1000
        self.swatch.configure(
            background=self.current_color,
            foreground="#111111" if brightness > 155 else "#ffffff",
        )
        if fields in {"all", "rgb"}:
            for variable, channel in zip(self.rgb_vars, (red, green, blue), strict=True):
                variable.set(str(channel))
        if fields in {"all", "hex"}:
            self.hex_var.set(self.current_color)

    def on_rgb_edit(self, _event=None) -> None:
        self.active_editor = "rgb"
        try:
            channels = tuple(int(variable.get().strip()) for variable in self.rgb_vars)
            color = rgb_to_hex(*channels)
        except (TypeError, ValueError):
            return
        self.update_preview(color, fields="hex", recalculate_hsv=True)

    def on_hex_edit(self, _event=None) -> None:
        self.active_editor = "hex"
        try:
            color = normalize_hex_color(self.hex_var.get())
        except ValueError:
            return
        self.update_preview(color, fields="rgb", recalculate_hsv=True)

    def set_palette_point(self, event) -> None:
        """Update the preview to the saturation/value point under the pointer."""
        if abs(self.hsv[0] - self.rendered_hue) > 0.0001:
            self.draw_palette(self.hsv[0])
        x = max(0, min(self.PALETTE_WIDTH - 1, event.x))
        y = max(0, min(self.PALETTE_HEIGHT - 1, event.y))
        self.hsv[1] = x / (self.PALETTE_WIDTH - 1)
        self.hsv[2] = 1.0 - y / (self.PALETTE_HEIGHT - 1)
        self.active_editor = None
        self.update_preview(hsv_to_hex(*self.hsv))

    def palette_motion(self, event) -> None:
        if not self.palette_locked:
            self.set_palette_point(event)

    def palette_click(self, event) -> None:
        self.set_palette_point(event)
        self.palette_locked = True

    def palette_leave(self, _event=None) -> None:
        self.palette_locked = False

    def set_hue_point(self, event) -> None:
        """Update the hue; update_preview redraws the square for it."""
        y = max(0, min(self.PALETTE_HEIGHT - 1, event.y))
        self.hsv[0] = y / (self.PALETTE_HEIGHT - 1)
        self.active_editor = None
        self.update_preview(hsv_to_hex(*self.hsv))

    def hue_motion(self, event) -> None:
        if not self.hue_locked:
            self.set_hue_point(event)

    def hue_click(self, event) -> None:
        self.set_hue_point(event)
        self.hue_locked = True

    def hue_leave(self, _event=None) -> None:
        self.hue_locked = False

    def cancel(self) -> None:
        self.apply_color(self.original_color)
        self.dialog.destroy()

    def save(self) -> None:
        try:
            if self.active_editor == "rgb":
                channels = tuple(int(variable.get().strip()) for variable in self.rgb_vars)
                color = rgb_to_hex(*channels)
            elif self.active_editor == "hex":
                color = normalize_hex_color(self.hex_var.get())
            else:
                color = self.current_color
            self.preference_store.save_slider_thumb_color(color)
            self.apply_color(color)
            self.status_var.set(f"Slider color saved ({color}).")
            self.dialog.destroy()
        except (TypeError, ValueError, SettingsError) as exc:
            messagebox.showerror(
                APP_NAME,
                f"Please enter a valid color. RGB values must be 0–255, or use a six-digit HEX value.\n\n{exc}",
                parent=self.dialog,
            )

    def reset_to_default(self) -> None:
        # Reset the live preview; Save color commits it, while Cancel still
        # restores the color that was active when this dialog opened.
        self.active_editor = None
        self.palette_locked = False
        self.hue_locked = False
        self.update_preview(PreferenceStore.DEFAULT_SLIDER_THUMB_COLOR, recalculate_hsv=True)
