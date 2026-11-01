"""Win32 calls for the taskbar identity and the window icon."""

import ctypes
import sys
from pathlib import Path

APP_USER_MODEL_ID = "AppVolumeManager.Desktop"
_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010


def set_app_user_model_id() -> None:
    """Give the source-run app its own Windows taskbar identity instead of Python's."""
    if sys.platform != "win32":
        return
    try:
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        setter(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        # The explicit window icon still provides a fallback.
        pass


def set_window_icon(hwnd: int, icon_path: Path) -> int | None:
    """Send an .ico file to a window as its small and large icon.

    Returns the icon handle, which must be released with destroy_icon(), or
    None if Windows did not load the file.
    """
    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.LoadImageW.restype = ctypes.c_void_p
    handle = user32.LoadImageW(None, str(icon_path), _IMAGE_ICON, 0, 0, _LR_LOADFROMFILE)
    if not handle:
        return None
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    window = ctypes.c_void_p(hwnd)
    icon = ctypes.c_void_p(handle)
    user32.SendMessageW(window, _WM_SETICON, ctypes.c_void_p(_ICON_SMALL), icon)
    user32.SendMessageW(window, _WM_SETICON, ctypes.c_void_p(_ICON_BIG), icon)
    return int(handle)


def destroy_icon(handle: int) -> None:
    if sys.platform != "win32":
        return
    try:
        destroy = ctypes.windll.user32.DestroyIcon
        destroy.argtypes = [ctypes.c_void_p]
        destroy.restype = ctypes.c_int
        destroy(ctypes.c_void_p(handle))
    except (AttributeError, OSError):
        pass
