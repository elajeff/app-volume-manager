"""Keep one volume controller per interactive Windows session."""

import ctypes
from ctypes import wintypes


MUTEX_NAME = r"Local\AppVolumeManager"
SHOW_EVENT_NAME = r"Local\AppVolumeManager.Show"


class SingleInstance:
    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self._kernel32.CreateEventW.restype = wintypes.HANDLE
        self._kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        self._kernel32.SetEvent.restype = wintypes.BOOL
        self._kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._mutex = None
        self._show_event = None

    def acquire(self, show_existing: bool = True) -> bool:
        # Auto-reset event: opening a second copy asks the first to show its UI.
        self._show_event = self._kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if not self._show_event:
            raise ctypes.WinError(ctypes.get_last_error())
        self._mutex = self._kernel32.CreateMutexW(None, False, MUTEX_NAME)
        error = ctypes.get_last_error()
        if not self._mutex:
            self.close()
            raise ctypes.WinError(error)
        already_running = error == 183  # ERROR_ALREADY_EXISTS
        if already_running and show_existing:
            self._kernel32.SetEvent(self._show_event)
        return not already_running

    def show_requested(self) -> bool:
        return self._kernel32.WaitForSingleObject(self._show_event, 0) == 0

    def close(self) -> None:
        for handle in (self._mutex, self._show_event):
            if handle:
                self._kernel32.CloseHandle(handle)
        self._mutex = self._show_event = None
