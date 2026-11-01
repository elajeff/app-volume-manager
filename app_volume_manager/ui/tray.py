"""System tray icon with Open, Reapply and Exit actions."""

from collections.abc import Callable
from pathlib import Path


def start_tray_icon(
    title: str,
    icon_path: Path,
    on_open: Callable,
    on_reapply: Callable,
    on_exit: Callable,
):
    """Show the tray icon on its own thread and return it.

    Raises if pystray or Pillow cannot start, so the caller can keep the
    window usable without a tray icon.
    """
    import pystray
    from PIL import Image

    with Image.open(icon_path) as source:
        image = source.convert("RGBA")
    menu = pystray.Menu(
        pystray.MenuItem("Open", on_open, default=True),
        pystray.MenuItem("Reapply saved volumes", on_reapply),
        pystray.MenuItem("Exit", on_exit),
    )
    icon = pystray.Icon("AppVolumeManager", image, title, menu)
    icon.run_detached()
    return icon
