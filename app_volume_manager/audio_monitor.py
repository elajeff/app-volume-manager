"""Event-driven notifications for newly created Windows playback sessions."""

from __future__ import annotations

import threading
from typing import Callable


class AudioSessionMonitor:
    """Register Core Audio callbacks so hidden mode need not poll every few seconds."""

    DEVICE_REFRESH_SECONDS = 30
    RETRY_SECONDS = 5

    def __init__(
        self,
        wrap_session: Callable,
        on_session_created: Callable,
        on_change: Callable[[], None],
    ) -> None:
        self._wrap_session = wrap_session
        self._on_session_created = on_session_created
        self._on_change = on_change
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status_lock = threading.Lock()
        self._ready = False
        self._last_error: str | None = None
        self._registrations: dict[str, tuple[object, object, str]] = {}
        self._index_lock = threading.Lock()
        self._callback_index = 0

    @property
    def is_ready(self) -> bool:
        with self._status_lock:
            return self._ready

    @property
    def last_error(self) -> str | None:
        with self._status_lock:
            return self._last_error

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="audio-session-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _set_status(self, ready: bool, error: str | None) -> None:
        with self._status_lock:
            changed = self._ready != ready or self._last_error != error
            self._ready = ready
            self._last_error = error
        if changed:
            self._signal_change()

    def _signal_change(self) -> None:
        try:
            self._on_change()
        except Exception:
            # An external callback must never terminate the COM listener thread.
            pass

    def _new_session(self, raw_session, endpoint_id: str, device_name: str) -> None:
        try:
            with self._index_lock:
                index = self._callback_index
                self._callback_index += 1
            session = self._wrap_session(raw_session, endpoint_id, device_name, index)
            if session is not None:
                # The COM session interface stays on its callback thread, so the
                # target volume can be applied before the GUI refreshes its list.
                self._on_session_created(session)
        except Exception:
            # The UI thread is still prompted to rescan and retry if possible.
            pass
        finally:
            self._signal_change()

    def _run(self) -> None:
        comtypes = None
        com_initialized = False
        try:
            import comtypes as comtypes_module

            comtypes = comtypes_module
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            com_initialized = True
            from pycaw.callbacks import AudioSessionNotification
            from pycaw.constants import DEVICE_STATE, EDataFlow
            from pycaw.pycaw import AudioUtilities

            class SessionCreatedCallback(AudioSessionNotification):
                def __init__(self, handler):
                    super().__init__()
                    self._handler = handler

                def on_session_created(self, new_session):
                    self._handler(new_session)

            while not self._stop_event.is_set():
                errors: list[str] = []
                try:
                    devices = AudioUtilities.GetAllDevices(
                        data_flow=EDataFlow.eRender.value,
                        device_state=DEVICE_STATE.ACTIVE.value,
                    )
                except Exception as exc:
                    devices = []
                    errors.append(f"Could not enumerate playback devices: {exc}")

                active_devices = {
                    str(getattr(device, "id", "")): device
                    for device in (devices or [])
                    if str(getattr(device, "id", ""))
                }
                changed = False

                # Unregister endpoints that disappeared or were disabled.
                for device_id in list(self._registrations):
                    if device_id not in active_devices:
                        manager, callback, _name = self._registrations.pop(device_id)
                        try:
                            manager.UnregisterSessionNotification(callback)
                        except Exception:
                            pass
                        changed = True

                # Register each active output once. GetCount() activates session
                # notifications according to Windows Core Audio's requirements.
                for device_id, device in active_devices.items():
                    if device_id in self._registrations:
                        continue
                    name = str(getattr(device, "FriendlyName", "Playback device") or "Playback device")
                    try:
                        manager = device.AudioSessionManager
                        callback = SessionCreatedCallback(
                            lambda session, eid=device_id, dname=name: self._new_session(
                                session, eid, dname
                            )
                        )
                        manager.RegisterSessionNotification(callback)
                        self._registrations[device_id] = (manager, callback, name)
                        manager.GetSessionEnumerator().GetCount()
                        changed = True
                    except Exception as exc:
                        errors.append(f"{name}: {exc}")
                        # Remove a partially registered entry so the next pass retries.
                        registration = self._registrations.pop(device_id, None)
                        if registration is not None:
                            try:
                                registration[0].UnregisterSessionNotification(registration[1])
                            except Exception:
                                pass

                self._set_status(bool(self._registrations), " | ".join(errors[:2]) or None)
                if changed:
                    self._signal_change()

                registration_healthy = self.is_ready and not errors
                interval = (
                    self.DEVICE_REFRESH_SECONDS if registration_healthy
                    else self.RETRY_SECONDS
                )
                self._stop_event.wait(interval)
        except Exception as exc:
            self._set_status(False, str(exc))
        finally:
            for manager, callback, _name in list(self._registrations.values()):
                try:
                    manager.UnregisterSessionNotification(callback)
                except Exception:
                    pass
            self._registrations.clear()
            if com_initialized and comtypes is not None:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass
            self._set_status(False, self.last_error)


def refresh_interval_ms(window_visible: bool, monitor_ready: bool) -> int:
    """Full session sweeps are frequent only while the user is viewing the list."""
    if window_visible:
        return 2000
    return 60000 if monitor_ready else 5000
