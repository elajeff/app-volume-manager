"""Enumerate Windows playback audio sessions and expose safe volume callbacks."""

import sys
import warnings
from pathlib import PureWindowsPath

from app_volume_manager.process_identity import identify_process_role
from app_volume_manager.volume_service import AudioSession


class AudioBackendError(RuntimeError):
    pass


class WindowsAudioBackend:
    def __init__(self) -> None:
        self._com_initialized = False
        self.last_warnings: list[str] = []

    def initialize(self) -> None:
        if sys.platform != "win32":
            raise AudioBackendError("App Volume Manager only works on Windows.")
        try:
            import comtypes

            comtypes.CoInitialize()
            self._com_initialized = True
        except Exception as exc:
            raise AudioBackendError(f"Could not initialize Windows audio access: {exc}") from exc

    def shutdown(self) -> None:
        if sys.platform != "win32" or not self._com_initialized:
            return
        try:
            import comtypes

            comtypes.CoUninitialize()
            self._com_initialized = False
        except Exception:
            # Safe during shutdown; Windows will clean up the process regardless.
            pass

    @staticmethod
    def _read_process(session):
        """Return PID, process object, and process name without dropping sessions needlessly."""
        process_id = None
        try:
            process_id = int(session.ProcessId)
        except Exception:
            # COM sessions can expire between enumeration and reading their PID.
            pass

        process = None
        try:
            process = session.Process
        except Exception:
            pass

        if process_id is None or process_id <= 0:
            try:
                process_id = int(process.pid) if process is not None else None
            except (AttributeError, TypeError, ValueError, OSError):
                process_id = None

        if process is None and process_id and process_id > 0:
            # Some transient or inaccessible sessions don't resolve through
            # pycaw's convenience property; try the underlying psutil lookup.
            try:
                import psutil

                process = psutil.Process(process_id)
            except Exception:
                process = None

        executable = ""
        executable_path = ""
        command_line = None
        if process is not None:
            try:
                executable = str(process.name() or "")
            except Exception:
                pass
            try:
                executable_path = str(process.exe() or "")
            except Exception:
                pass
            try:
                command_line = process.cmdline()
            except Exception:
                command_line = None

        if not executable and executable_path:
            executable = PureWindowsPath(executable_path).name
        if not executable and process_id and process_id > 0:
            # Keep the row visible for diagnosis instead of silently dropping a
            # valid audio session because its process metadata was inaccessible.
            executable = f"Unknown process {process_id}.exe"
        if not executable:
            return None

        signature, role = identify_process_role(executable, command_line)
        return process_id, executable, executable_path, signature, role

    def wrap_notified_session(self, raw_session, endpoint_id: str, device_name: str, index: int):
        """Wrap a session delivered by Core Audio's session-created callback.

        This runs on the COM callback thread so the session interface is not
        handed across apartments before its saved volume rule is applied.
        """
        try:
            from pycaw.pycaw import AudioSession as PycawAudioSession, IAudioSessionControl2

            control2 = raw_session.QueryInterface(IAudioSessionControl2)
            session = PycawAudioSession(control2)
            return self._wrap_session(session, endpoint_id, device_name, index)
        except Exception:
            # The regular enumeration path will retry if this transient session
            # cannot be wrapped directly.
            return None

    def _wrap_session(self, session, endpoint_id: str, device_name: str, index: int):
        process_details = self._read_process(session)
        if process_details is None:
            return None
        process_id, executable, executable_path, signature, role = process_details

        try:
            instance_identifier = str(session.InstanceIdentifier or "")
        except Exception:
            instance_identifier = ""
        try:
            session_identifier = str(session.Identifier or "")
        except Exception:
            session_identifier = ""
        if not instance_identifier:
            instance_identifier = f"pid:{process_id}:index:{index}:id:{session_identifier}"

        try:
            current_volume = round(float(session.SimpleAudioVolume.GetMasterVolume()) * 100)
        except Exception:
            current_volume = None
        try:
            session_name = str(session.DisplayName or "").strip()
        except Exception:
            session_name = ""

        volume_control = session.SimpleAudioVolume

        def set_volume(percent: int, volume=volume_control) -> None:
            volume.SetMasterVolume(max(0, min(100, percent)) / 100.0, None)

        return AudioSession(
            executable=executable,
            session_id=f"{endpoint_id}|{instance_identifier}",
            set_volume=set_volume,
            process_id=process_id,
            current_volume=current_volume,
            process_signature=signature,
            process_role=role,
            session_name=session_name,
            device_name=device_name,
        )

    def get_sessions(self) -> list[AudioSession]:
        if sys.platform != "win32":
            raise AudioBackendError("Audio session monitoring is available on Windows only.")

        try:
            from pycaw.constants import DEVICE_STATE, EDataFlow
            from pycaw.pycaw import AudioSession as PycawAudioSession, AudioUtilities, IAudioSessionControl2
        except ImportError as exc:
            raise AudioBackendError(
                "The audio dependencies are missing. Run run.bat to install requirements.txt."
            ) from exc

        collected: list[AudioSession] = []
        device_errors: list[str] = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                devices = AudioUtilities.GetAllDevices(
                    data_flow=EDataFlow.eRender.value,
                    device_state=DEVICE_STATE.ACTIVE.value,
                )
        except Exception as exc:
            devices = []
            device_errors.append(f"Could not enumerate playback devices: {exc}")

        # Query every active render endpoint so applications routed to headphones
        # or a communications device appear too, not just the default speaker.
        for device in devices or []:
            device_name = str(getattr(device, "FriendlyName", "Playback device") or "Playback device")
            endpoint_id = str(getattr(device, "id", "unknown-device"))
            try:
                enumerator = device.AudioSessionManager.GetSessionEnumerator()
                for index in range(enumerator.GetCount()):
                    try:
                        control = enumerator.GetSession(index)
                        if control is None:
                            continue
                        control2 = control.QueryInterface(IAudioSessionControl2)
                        session = PycawAudioSession(control2)
                        wrapped = self._wrap_session(session, endpoint_id, device_name, index)
                        if wrapped is not None:
                            collected.append(wrapped)
                    except Exception as exc:
                        device_errors.append(f"{device_name}, session {index}: {exc}")
            except Exception as exc:
                device_errors.append(f"{device_name}: {exc}")

        # Pycaw's documented helper is a compatibility fallback for its default
        # output endpoint. This covers setups where per-device enumeration
        # differs across Pycaw/Windows audio-stack versions.
        if not collected:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    fallback_sessions = AudioUtilities.GetAllSessions()
                for index, session in enumerate(fallback_sessions or []):
                    wrapped = self._wrap_session(
                        session, "default-output", "Default playback device", index
                    )
                    if wrapped is not None:
                        collected.append(wrapped)
            except Exception as exc:
                device_errors.append(f"Default-output fallback failed: {exc}")

        # De-duplicate by endpoint + session instance. Keep the same process PID
        # visible as a single process row in process_list.py, while preserving all
        # audio sessions in the backend for volume application.
        unique: dict[str, AudioSession] = {}
        for session in collected:
            unique.setdefault(session.session_id, session)

        self.last_warnings = device_errors[:3]
        if not unique and device_errors:
            raise AudioBackendError("Could not read Windows audio sessions: " + " | ".join(device_errors[:3]))
        return list(unique.values())
