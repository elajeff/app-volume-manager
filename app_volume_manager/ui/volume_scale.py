"""Helpers shared by the volume sliders."""

import tkinter as tk


def percent(value) -> int:
    """Round a slider value to a whole percentage from 0 to 100."""
    return max(0, min(100, int(float(value) + 0.5)))


def allow_scale_thumb_click(event) -> str | None:
    """Allow mouse interaction only when the pointer is on the scale thumb.

    Returning ``break`` for clicks on the trough prevents ttk.Scale's default
    behavior of jumping to the clicked position. Native arrow-key handling is
    unaffected, and clicks/drags that begin on the thumb keep the default binding.
    """
    try:
        element = str(event.widget.identify(event.x, event.y)).casefold()
    except (AttributeError, tk.TclError):
        return "break"
    if "slider" in element or "thumb" in element:
        return None
    return "break"
