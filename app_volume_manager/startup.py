"""Register or remove the app from the current user's Windows sign-in startup."""

import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "AppVolumeManager"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable, "--minimized"])

    script = Path(sys.argv[0]).resolve()
    python_path = Path(sys.executable)
    pythonw_path = python_path.with_name("pythonw.exe")
    interpreter = pythonw_path if pythonw_path.exists() else python_path
    return subprocess.list2cmdline([str(interpreter), str(script), "--minimized"])


def is_startup_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
            return value == _startup_command()
    except FileNotFoundError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Automatic startup is only supported on Windows.")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_VALUE_NAME)
            except FileNotFoundError:
                pass
