import sys
import types
import unittest
from unittest.mock import patch

from app_volume_manager.audio_backend import WindowsAudioBackend


class _Volume:
    def __init__(self, value=0.35):
        self.value = value
        self.set_values = []

    def GetMasterVolume(self):
        return self.value

    def SetMasterVolume(self, value, _context):
        self.value = value
        self.set_values.append(value)


class _Process:
    def __init__(self, pid, name="Discord.exe", cmdline=None):
        self.pid = pid
        self._name = name
        self._cmdline = cmdline or [name]

    def name(self):
        return self._name

    def exe(self):
        return rf"C:\Apps\{self._name}"

    def cmdline(self):
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


if __name__ == "__main__":
    unittest.main()
