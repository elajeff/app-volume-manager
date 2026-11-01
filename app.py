"""Windows per-application volume manager."""

import argparse
import logging
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler

from app_volume_manager.settings import default_settings_path
from app_volume_manager.single_instance import SingleInstance
from app_volume_manager.ui import APP_NAME
from app_volume_manager.ui.main_window import VolumeManagerApp
from app_volume_manager.ui.windows_shell import set_app_user_model_id


def configure_logging() -> None:
    """Keep a small log of warnings and errors next to the settings file."""
    log_path = default_settings_path().with_name("app.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=200_000, backupCount=1, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler])


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--minimized", action="store_true", help="Start hidden in the system tray")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("App Volume Manager is a Windows-only application.", file=sys.stderr)
        return 1
    instance = SingleInstance()
    try:
        if not instance.acquire(show_existing=not args.minimized):
            return 0
        configure_logging()
        set_app_user_model_id()
        root = tk.Tk()
        VolumeManagerApp(root, instance, start_minimized=args.minimized)
        root.mainloop()
        return 0
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
