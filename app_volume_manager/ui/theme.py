"""Light and dark palettes and the ttk styles that use them."""

import tkinter as tk
from tkinter import ttk

PALETTES = {
    "light": {
        "background": "#f3f5f8", "panel": "#ffffff", "text": "#202938",
        "muted": "#5d6878", "field": "#ffffff", "border": "#d4dce7",
        "selected": "#d8e8ff", "heading": "#e8edf4", "accent": "#356cc4",
        "trough": "#d9e0e9",
    },
    "dark": {
        "background": "#171a21", "panel": "#222733", "text": "#e8edf5",
        "muted": "#b1bbcb", "field": "#1c212b", "border": "#3b4555",
        "selected": "#344c70", "heading": "#2b3240", "accent": "#8ab4f8",
        "trough": "#3b4555",
    },
}


def apply_base_theme(root: tk.Tk, theme: str) -> tuple[ttk.Style, dict[str, str]]:
    """Apply the palette for `theme` to every standard ttk widget.

    The volume slider and scrollbars depend on the user's chosen color, so
    configure_volume_slider() and configure_scrollbars() run after this.
    """
    colors = PALETTES[theme]
    root.configure(background=colors["background"])
    style = ttk.Style(root)
    try:
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        ".", font=("Segoe UI", 9), background=colors["background"],
        foreground=colors["text"],
    )
    style.configure("TFrame", background=colors["background"])
    style.configure("TLabel", background=colors["background"], foreground=colors["text"])
    style.configure(
        "TButton", padding=(10, 5), background=colors["panel"],
        foreground=colors["text"], bordercolor=colors["border"],
    )
    style.map(
        "TButton",
        background=[("disabled", colors["background"]), ("active", colors["heading"])],
        foreground=[("disabled", colors["muted"])],
    )
    style.configure("TCheckbutton", background=colors["background"], foreground=colors["text"])
    style.map("TCheckbutton", background=[("active", colors["background"])])
    style.configure(
        "TEntry", fieldbackground=colors["field"], foreground=colors["text"],
        bordercolor=colors["border"],
    )
    style.configure(
        "TCombobox", fieldbackground=colors["field"], background=colors["panel"],
        foreground=colors["text"], arrowcolor=colors["text"],
        bordercolor=colors["border"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", colors["field"])],
        foreground=[("readonly", colors["text"])],
        selectbackground=[("readonly", colors["field"])],
        selectforeground=[("readonly", colors["text"])],
    )
    style.configure(
        "Treeview", background=colors["field"], fieldbackground=colors["field"],
        foreground=colors["text"], rowheight=27, bordercolor=colors["border"],
    )
    style.map(
        "Treeview", background=[("selected", colors["selected"])],
        foreground=[("selected", colors["text"])],
    )
    style.configure(
        "Treeview.Heading", background=colors["heading"], foreground=colors["text"],
        relief="flat", padding=(6, 6),
    )
    style.map("Treeview.Heading", background=[("active", colors["panel"])])
    style.configure(
        "Horizontal.TScale", background=colors["background"],
        troughcolor=colors["trough"],
    )
    return style, colors


def configure_scrollbars(style: ttk.Style, colors: dict[str, str], slider_color: str) -> None:
    """Use the selected slider color for both process-list scrollbars."""
    for orientation in ("Vertical", "Horizontal"):
        style_name = f"App.{orientation}.TScrollbar"
        style.configure(
            style_name,
            background=slider_color,
            troughcolor=colors["trough"],
            bordercolor=colors["border"],
            lightcolor=slider_color,
            darkcolor=slider_color,
            arrowcolor=slider_color,
            relief="flat",
        )
        style.map(
            style_name,
            background=[
                ("active", slider_color),
                ("pressed", slider_color),
                ("disabled", slider_color),
            ],
        )


def configure_volume_slider(style: ttk.Style, colors: dict[str, str], slider_color: str) -> None:
    """Use the same customizable, high-contrast slider in both themes."""
    style.configure(
        "Volume.Horizontal.TScale",
        background=slider_color,
        troughcolor=colors["trough"],
        bordercolor=slider_color,
        lightcolor=slider_color,
        darkcolor=slider_color,
        focuscolor=slider_color,
        borderwidth=0,
        sliderlength=22,
        sliderthickness=16,
        # A flat thumb avoids the light/dark bevel spots drawn by the
        # classic raised style, making the slider look like a single solid fill.
        sliderrelief="flat",
    )
    style.map(
        "Volume.Horizontal.TScale",
        background=[("active", slider_color), ("disabled", slider_color)],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
