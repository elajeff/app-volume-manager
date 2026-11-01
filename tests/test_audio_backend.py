import sys
import types
import unittest
from unittest.mock import patch

from app_volume_manager.audio_backend import WindowsAudioBackend


class _Volume:
    def __init__(self, value=0.35):
        self.value = value
        self.set_values = []
        self.contexts = []

    def GetMasterVolume(self):
        return self.value

    def SetMasterVolume(self, value, context):
        self.value = value
        self.set_values.append(value)
        self.contexts.append(context)


class _Process:
    def __init__(self, pid, name="Discord.exe", cmdline=None):
        self.pid = pid
        self._name = name
        self._cmdline = cmdline or [name]
        self.started = 1.0
        self.cmdline_reads = 0
        self.cmdline_error = None

    def create_time(self):
        return self.started

    def name(self):
        return self._name

    def exe(self):
        return rf"C:\Apps\{self._name}"

    def cmdline(self):
        self.cmdline_reads += 1
        if self.cmdline_error:
            raise self.cmdline_error
        return self._cmdline


class _Session:
    def __init__(self, pid=120, name="Discord.exe", cmdline=None, display="Discord audio"):
        self.ProcessId = pid
        self.Process = _Process(pid, name, cmdline or [name])
        self.InstanceIdentifier = f"session-instance-{pid}"
        self.Identifier = f"session-identifier-{pid}"
        self.DisplayName = display
        self.SimpleAudioVolume = _Volume()

    def QueryInterface(self, _interface):
        return self


class _Enumerator:
    def GetCount(self):
        return 0


class _Manager:
    def GetSessionEnumerator(self):
        return _Enumerator()


class _Device:
    id = "device-1"
    FriendlyName = "Test Speakers"
    AudioSessionManager = _Manager()


class AudioBackendTests(unittest.TestCase):
    def fake_pycaw(self, devices, sessions):
        constants = types.ModuleType("pycaw.constants")
        constants.DEVICE_STATE = types.SimpleNamespace(ACTIVE=types.SimpleNamespace(value=1))
        constants.EDataFlow = types.SimpleNamespace(eRender=types.SimpleNamespace(value=0))
        pycaw = types.ModuleType("pycaw.pycaw")
        pycaw.AudioSession = lambda item: item
        pycaw.IAudioSessionControl2 = object
        pycaw.AudioUtilities = types.SimpleNamespace(
            GetAllDevices=lambda **_kwargs: devices,
            GetAllSessions=lambda: sessions,
        )
        package = types.ModuleType("pycaw")
        package.__path__ = []
        return {"pycaw": package, "pycaw.constants": constants, "pycaw.pycaw": pycaw}

    def test_falls_back_to_documented_default_output_enumeration(self):
        session = _Session(pid=123, cmdline=["Discord.exe", "--type=renderer"])
        modules = self.fake_pycaw([_Device()], [session])
        backend = WindowsAudioBackend()
        with patch("sys.platform", "win32"), patch.dict(sys.modules, modules):
            result = backend.get_sessions()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].process_id, 123)
        self.assertEqual(result[0].executable, "Discord.exe")
        self.assertEqual(result[0].process_role, "Renderer process")
        self.assertEqual(result[0].current_volume, 35)
        self.assertEqual(result[0].device_name, "Default playback device")
        result[0].set_volume(20)
        self.assertEqual(session.SimpleAudioVolume.set_values, [0.2])

    def test_notification_accepts_pycaw_wrapper_without_querying_it_again(self):
        # Real Pycaw wrappers have no QueryInterface method.
        class WrappedSession(_Session):
            QueryInterface = None
        session = WrappedSession(pid=123)
        modules = self.fake_pycaw([], [])
        modules["pycaw.pycaw"].AudioSession = WrappedSession
        with patch.dict(sys.modules, modules):
            result = WindowsAudioBackend().wrap_notified_session(session, "device-1", "Speakers", 0)
        self.assertIsNotNone(result)
        result.set_volume(15)
        self.assertEqual(session.SimpleAudioVolume.set_values, [0.15])

    def test_enumerates_sessions_from_all_devices_without_fallback(self):
        session = _Session(pid=555, cmdline=["Discord.exe"])
        class SessionEnumerator:
            def GetCount(self):
                return 1
            def GetSession(self, _index):
                return session
        class Manager:
            def GetSessionEnumerator(self):
                return SessionEnumerator()
        device = _Device()
        device.AudioSessionManager = Manager()
        modules = self.fake_pycaw([device], [session])
        backend = WindowsAudioBackend()
        with patch("sys.platform", "win32"), patch.dict(sys.modules, modules):
            result = backend.get_sessions()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].process_id, 555)
        self.assertEqual(result[0].device_name, "Test Speakers")
        self.assertEqual(result[0].process_signature, "discord.exe|main")

    def sweep(self, backend, sessions):
        """Run get_sessions against a freshly listed device whose only sessions are `sessions`."""
        backend.invalidate_devices()
        class Manager:
            def GetSessionEnumerator(self):
                return types.SimpleNamespace(GetCount=lambda: len(sessions), GetSession=lambda i: sessions[i])
        device = _Device()
        device.AudioSessionManager = Manager()
        modules = self.fake_pycaw([device], [])
        with patch("sys.platform", "win32"), patch.dict(sys.modules, modules):
            return backend.get_sessions()

    def test_devices_are_listed_once_until_invalidated(self):
        listings = []
        modules = self.fake_pycaw([_Device()], [])
        modules["pycaw.pycaw"].AudioUtilities.GetAllDevices = lambda **_kwargs: listings.append(1) or [_Device()]
        backend = WindowsAudioBackend()
        with patch("sys.platform", "win32"), patch.dict(sys.modules, modules):
            backend.get_sessions()
            backend.get_sessions()
            self.assertEqual(len(listings), 1)
            backend.invalidate_devices()
            backend.get_sessions()
        self.assertEqual(len(listings), 2)

    def test_a_failing_device_forces_a_fresh_listing(self):
        class BrokenDevice(_Device):
            @property
            def AudioSessionManager(self):
                raise OSError("device removed")
        backend = WindowsAudioBackend()
        modules = self.fake_pycaw([BrokenDevice()], [_Session(pid=7)])
        with patch("sys.platform", "win32"), patch.dict(sys.modules, modules):
            backend.get_sessions()
        self.assertIsNone(backend._devices)

    def test_process_identity_is_read_once_per_process_start(self):
        session = _Session(pid=555, cmdline=["Discord.exe", "--type=renderer"])
        backend = WindowsAudioBackend()
        first = self.sweep(backend, [session])
        second = self.sweep(backend, [session])
        self.assertEqual(session.Process.cmdline_reads, 1)
        self.assertEqual(first[0].process_signature, second[0].process_signature)
        self.assertEqual(second[0].process_role, "Renderer process")
        session.Process.started = 2.0  # The PID was reused by a new process.
        self.sweep(backend, [session])
        self.assertEqual(session.Process.cmdline_reads, 2)

    def test_unreadable_command_lines_are_retried_and_closed_processes_forgotten(self):
        session = _Session(pid=555)
        session.Process.cmdline_error = PermissionError("starting up")
        backend = WindowsAudioBackend()
        self.sweep(backend, [session])
        self.sweep(backend, [session])
        self.assertEqual(session.Process.cmdline_reads, 2)
        session.Process.cmdline_error = None
        self.sweep(backend, [session])
        self.assertIn(555, backend._identities)
        self.sweep(backend, [])
        self.assertEqual(backend._identities, {})


if __name__ == "__main__":
    unittest.main()
