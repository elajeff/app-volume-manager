"""Modal Tk color editor for the volume slider."""

import colorsys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app_volume_manager.color_utils import (
    hex_to_rgb, hsv_to_hex, normalize_hex_color, rgb_to_hex,
)
from app_volume_manager.settings import PreferenceStore, SettingsError

APP_NAME = "App Volume Manager"
DEFAULT_SLIDER_THUMB_COLOR = PreferenceStore.DEFAULT_SLIDER_THUMB_COLOR


def show_slider_color_dialog(
    parent: tk.Misc,
    original_color: str,
    preference_store: PreferenceStore,
    apply_color: Callable[[str], None],
    status_var: tk.StringVar,
) -> None:
    """Show a live color picker; Save persists the preview and Cancel reverts it."""
    original_color = normalize_hex_color(original_color)
    current_color = original_color
    active_editor: str | None = None
    syncing_fields = False
    current_rgb = hex_to_rgb(current_color)
    initial_hsv = colorsys.rgb_to_hsv(*(channel / 255 for channel in current_rgb))
    hsv = [initial_hsv[0], initial_hsv[1], initial_hsv[2]]

    dialog = tk.Toplevel(parent)
    dialog.title("Customize slider color")
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.protocol("WM_DELETE_WINDOW", lambda: cancel())

    frame = ttk.Frame(dialog, padding=14)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="Hover to preview. Click a point to keep its color while moving away; leave and re-enter to preview again. Drag to adjust continuously.",
        wraplength=430,
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    palette_width, palette_height = 230, 160
    hue_width = 18
    palette_canvas = tk.Canvas(
        frame, width=palette_width, height=palette_height,
        highlightthickness=1, highlightbackground="#7b8492", bd=0,
    )
    palette_canvas.grid(row=1, column=0, sticky="n")
    hue_canvas = tk.Canvas(
        frame, width=hue_width, height=palette_height,
        highlightthickness=1, highlightbackground="#7b8492", bd=0,
    )
    hue_canvas.grid(row=1, column=1, sticky="n", padx=(7, 14))

    fields_frame = ttk.Frame(frame)
    fields_frame.grid(row=1, column=2, sticky="n")
    ttk.Label(fields_frame, text="RGB values").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
    )
    rgb_vars = [tk.StringVar(value=str(channel)) for channel in current_rgb]
    for row_index, (label, variable) in enumerate(zip(("Red", "Green", "Blue"), rgb_vars), start=1):
        ttk.Label(fields_frame, text=label).grid(row=row_index, column=0, sticky="w", padx=(0, 8))
        entry = ttk.Entry(fields_frame, textvariable=variable, width=6, justify="right")
        entry.grid(row=row_index, column=1, sticky="ew", pady=2)
        entry.bind("<FocusIn>", lambda event: event.widget.selection_range(0, "end"))

    ttk.Label(fields_frame, text="HEX value").grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(9, 2)
    )
    hex_var = tk.StringVar(value=current_color)
    hex_entry = ttk.Entry(fields_frame, textvariable=hex_var, width=12)
    hex_entry.grid(row=5, column=0, columnspan=2, sticky="ew")
    hex_entry.bind("<FocusIn>", lambda event: event.widget.selection_range(0, "end"))
    swatch = tk.Label(
        fields_frame, text="Preview", bg=current_color, fg="white",
        relief="solid", bd=1, padx=12, pady=5,
    )
    swatch.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    palette_photo = tk.PhotoImage(master=dialog, width=palette_width, height=palette_height)
    hue_photo = tk.PhotoImage(master=dialog, width=hue_width, height=palette_height)
    palette_canvas.create_image(0, 0, image=palette_photo, anchor="nw")
    hue_canvas.create_image(0, 0, image=hue_photo, anchor="nw")
    # Keep explicit references while the modal dialog is open.
    dialog.palette_photo = palette_photo
    dialog.hue_photo = hue_photo
    rendered_hue = -1.0
    # Hover previews are convenient, but once a user clicks a point, keep
    # that choice fixed while they move the pointer away to Save. Leaving
    # and re-entering the same canvas enables hover previews again.
    palette_locked = False
    hue_locked = False

    def draw_palette(hue: float) -> None:
        nonlocal rendered_hue
        for y in range(palette_height):
            value = 1.0 - y / (palette_height - 1)
            row_colors = [
                hsv_to_hex(hue, x / (palette_width - 1), value)
                for x in range(palette_width)
            ]
            palette_photo.put("{" + " ".join(row_colors) + "}", to=(0, y))
        rendered_hue = hue

    def draw_hue_strip() -> None:
        for y in range(palette_height):
            hue_color = hsv_to_hex(y / (palette_height - 1), 1.0, 1.0)
            hue_photo.put(
                "{" + " ".join([hue_color] * hue_width) + "}", to=(0, y)
            )

    def draw_palette_marker() -> None:
        """Show the current saturation/value point on the large color square."""
        palette_canvas.delete("palette-marker")
        x = round(hsv[1] * (palette_width - 1))
        y = round((1.0 - hsv[2]) * (palette_height - 1))
        # A dark outline plus a short white center stays visible on most colors.
        palette_canvas.create_line(
            x - 7, y, x + 7, y, fill="#101010", width=3,
            tags="palette-marker",
        )
        palette_canvas.create_line(
            x, y - 7, x, y + 7, fill="#101010", width=3,
            tags="palette-marker",
        )
        palette_canvas.create_line(
            x - 6, y, x + 6, y, fill="#FFFFFF", width=1,
            tags="palette-marker",
        )
        palette_canvas.create_line(
            x, y - 6, x, y + 6, fill="#FFFFFF", width=1,
            tags="palette-marker",
        )

    def draw_hue_marker(hue: float) -> None:
        """Keep a high-contrast line at the currently selected hue."""
        hue_canvas.delete("hue-marker")
        y = round((hue % 1.0) * (palette_height - 1))
        if y > 0:
            hue_canvas.create_line(
                0, y - 1, hue_width, y - 1, fill="#101010", width=1,
                tags="hue-marker",
            )
        hue_canvas.create_line(
            0, y, hue_width, y, fill="#FFFFFF", width=2,
            tags="hue-marker",
        )
        if y < palette_height - 1:
            hue_canvas.create_line(
                0, y + 1, hue_width, y + 1, fill="#101010", width=1,
                tags="hue-marker",
            )

    def update_preview(
        color: str, fields: str = "all", recalculate_hsv: bool = False
    ) -> None:
        nonlocal current_color, syncing_fields
        current_color = normalize_hex_color(color)
        apply_color(current_color)
        red, green, blue = hex_to_rgb(current_color)
        if recalculate_hsv:
            new_hsv = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            hsv[:] = new_hsv
        # Editing RGB/HEX changes the hue too, so keep both color surfaces
        # and their position indicators synchronized with the live preview.
        if abs(hsv[0] - rendered_hue) > 0.0001:
            draw_palette(hsv[0])
        draw_palette_marker()
        draw_hue_marker(hsv[0])
        brightness = (red * 299 + green * 587 + blue * 114) / 1000
        swatch.configure(
            background=current_color,
            foreground="#111111" if brightness > 155 else "#ffffff",
        )
        syncing_fields = True
        try:
            if fields in {"all", "rgb"}:
                for variable, channel in zip(rgb_vars, (red, green, blue)):
                    variable.set(str(channel))
            if fields in {"all", "hex"}:
                hex_var.set(current_color)
        finally:
            syncing_fields = False

    def on_rgb_edit(_event=None) -> None:
        nonlocal active_editor
        if syncing_fields:
            return
        active_editor = "rgb"
        try:
            channels = tuple(int(variable.get().strip()) for variable in rgb_vars)
            color = rgb_to_hex(*channels)
        except (TypeError, ValueError):
            return
        update_preview(color, fields="hex", recalculate_hsv=True)

    def on_hex_edit(_event=None) -> None:
        nonlocal active_editor
        if syncing_fields:
            return
        active_editor = "hex"
        try:
            color = normalize_hex_color(hex_var.get())
        except ValueError:
            return
        update_preview(color, fields="rgb", recalculate_hsv=True)

    for child in fields_frame.winfo_children():
        if isinstance(child, ttk.Entry) and child is not hex_entry:
            child.bind("<KeyRelease>", on_rgb_edit)
            child.bind("<Return>", on_rgb_edit)
            child.bind("<FocusOut>", on_rgb_edit)
    hex_entry.bind("<KeyRelease>", on_hex_edit)
    hex_entry.bind("<Return>", on_hex_edit)
    hex_entry.bind("<FocusOut>", on_hex_edit)

    def set_palette_point(event) -> None:
        """Update the preview to the saturation/value point under the pointer."""
        nonlocal active_editor
        if abs(hsv[0] - rendered_hue) > 0.0001:
            draw_palette(hsv[0])
        x = max(0, min(palette_width - 1, event.x))
        y = max(0, min(palette_height - 1, event.y))
        hsv[1] = x / (palette_width - 1)
        hsv[2] = 1.0 - y / (palette_height - 1)
        active_editor = None
        update_preview(hsv_to_hex(*hsv))

    def palette_motion(event) -> None:
        if not palette_locked:
            set_palette_point(event)

    def palette_click(event) -> None:
        nonlocal palette_locked
        set_palette_point(event)
        palette_locked = True

    def palette_drag(event) -> None:
        # Dragging intentionally changes the selection, even after a click.
        set_palette_point(event)

    def palette_leave(_event=None) -> None:
        nonlocal palette_locked
        palette_locked = False

    def set_hue_point(event) -> None:
        """Update the hue and redraw the square for the current hue."""
        nonlocal active_editor
        y = max(0, min(palette_height - 1, event.y))
        hsv[0] = y / (palette_height - 1)
        active_editor = None
        # Immediately redraw the large square as the hue changes. Previously
        # its colors stayed stale until the pointer moved back over the square.
        if abs(hsv[0] - rendered_hue) > 0.0001:
            draw_palette(hsv[0])
        draw_hue_marker(hsv[0])
        update_preview(hsv_to_hex(*hsv))

    def hue_motion(event) -> None:
        if not hue_locked:
            set_hue_point(event)

    def hue_click(event) -> None:
        nonlocal hue_locked
        set_hue_point(event)
        hue_locked = True

    def hue_drag(event) -> None:
        # Dragging intentionally changes the selection, even after a click.
        set_hue_point(event)

    def hue_leave(_event=None) -> None:
        nonlocal hue_locked
        hue_locked = False

    palette_canvas.bind("<Motion>", palette_motion)
    palette_canvas.bind("<Button-1>", palette_click)
    palette_canvas.bind("<B1-Motion>", palette_drag)
    palette_canvas.bind("<Leave>", palette_leave)
    hue_canvas.bind("<Motion>", hue_motion)
    hue_canvas.bind("<Button-1>", hue_click)
    hue_canvas.bind("<B1-Motion>", hue_drag)
    hue_canvas.bind("<Leave>", hue_leave)
    draw_palette(hsv[0])
    draw_hue_strip()
    draw_palette_marker()
    draw_hue_marker(hsv[0])

    ttk.Label(
        frame,
        text="RGB accepts whole numbers from 0 to 255. HEX accepts #RRGGBB.",
        foreground="#687386",
    ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(9, 0))

    buttons = ttk.Frame(frame)
    buttons.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))

    def cancel() -> None:
        apply_color(original_color)
        dialog.destroy()

    def save() -> None:
        try:
            if active_editor == "rgb":
                channels = tuple(int(variable.get().strip()) for variable in rgb_vars)
                color = rgb_to_hex(*channels)
            elif active_editor == "hex":
                color = normalize_hex_color(hex_var.get())
            else:
                color = current_color
            preference_store.save_slider_thumb_color(color)
            apply_color(color)
            status_var.set(f"Slider color saved ({color}).")
            dialog.destroy()
        except (TypeError, ValueError, SettingsError) as exc:
            messagebox.showerror(
                APP_NAME,
                f"Please enter a valid color. RGB values must be 0–255, or use a six-digit HEX value.\n\n{exc}",
                parent=dialog,
            )

    def reset_to_default() -> None:
        nonlocal active_editor, palette_locked, hue_locked
        # Reset the live preview; Save color commits it, while Cancel still
        # restores the color that was active when this dialog opened.
        active_editor = None
        palette_locked = False
        hue_locked = False
        update_preview(DEFAULT_SLIDER_THUMB_COLOR, recalculate_hsv=True)

    ttk.Button(
        buttons, text="Reset to default", command=reset_to_default
    ).pack(side="left")
    ttk.Button(buttons, text="Cancel", command=cancel).pack(side="right", padx=(6, 0))
    ttk.Button(buttons, text="Save color", command=save).pack(side="right")
    dialog.bind("<Escape>", lambda _event: cancel())
    dialog.bind("<Return>", lambda _event: save())
    dialog.grab_set()
    parent.wait_window(dialog)

