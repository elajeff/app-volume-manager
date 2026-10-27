import unittest
from unittest.mock import Mock

from app_volume_manager.audio_monitor import AudioSessionMonitor, refresh_interval_ms
from app_volume_manager.volume_service import AudioSession


class AudioMonitorTests(unittest.TestCase):
    def test_new_session_is_wrapped_applied_and_signals_gui(self):
        session = AudioSession("discord.exe", "session-1", lambda _value: None)
        applied, changed = [], Mock()
        monitor = AudioSessionMonitor(
            wrap_session=lambda *_args: session,
            on_session_created=applied.append,
            on_change=changed,
        )
        monitor._new_session(object(), "device-1", "Speakers")
        self.assertEqual(applied, [session])
        changed.assert_called_once_with()

    def test_visible_and_hidden_refresh_intervals(self):
        self.assertEqual(refresh_interval_ms(True, True), 2_000)
        self.assertEqual(refresh_interval_ms(True, False), 2_000)
        self.assertEqual(refresh_interval_ms(False, True), 60_000)
        self.assertEqual(refresh_interval_ms(False, False), 5_000)


class NotificationLifecycleTests(unittest.TestCase):
    def test_volume_changes_wake_scan_and_device_change_registers_new_output(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        class Session:
            State = 1
            def __init__(self, identifier):
                self.InstanceIdentifier = identifier
                self.callback = None
                self.unregistered = False
            def QueryInterface(self, _interface):
                return self
            def register_notification(self, callback):
                self.callback = callback
            def unregister_notification(self):
                self.unregistered = True

        class Manager:
            def __init__(self, session):
                self.session = session
                self.callback = None
                self.unregistered = False
            def RegisterSessionNotification(self, callback):
                self.callback = callback
            def UnregisterSessionNotification(self, callback):
                self.unregistered = True
            def GetSessionEnumerator(self):
                return SimpleNamespace(GetCount=lambda: 1, GetSession=lambda index: self.session)

        first, second = Session("one"), Session("two")
        manager1, manager2 = Manager(first), Manager(second)
        devices = [SimpleNamespace(id="speakers", AudioSessionManager=manager1)]
        endpoint_enumerator = Mock()
        changed, applied = Mock(), Mock()
        monitor = AudioSessionMonitor(
            wrap_session=lambda raw, *_args: AudioSession("Discord.exe", raw.InstanceIdentifier, lambda _: None),
            on_session_created=applied,
            on_change=changed,
        )
        calls = []
        def wait(_interval):
            calls.append(True)
            if len(calls) == 1:
                before = changed.call_count
                first.callback.on_simple_volume_changed(1.0, 0, None)
                self.assertGreater(changed.call_count, before)
                devices.append(SimpleNamespace(id="headset", AudioSessionManager=manager2))
                endpoint_enumerator.RegisterEndpointNotificationCallback.call_args.args[0].on_device_added("headset")
                self.assertTrue(monitor._refresh_event.is_set())
                manager1.callback.on_session_created(Session("new-voice"))
            else:
                monitor._stop_event.set()
        constants = SimpleNamespace(
            DEVICE_STATE=SimpleNamespace(ACTIVE=SimpleNamespace(value=1)),
            EDataFlow=SimpleNamespace(eRender=SimpleNamespace(value=0)),
        )
        utilities = SimpleNamespace(
            GetDeviceEnumerator=lambda: endpoint_enumerator,
            GetAllDevices=lambda **_kwargs: devices,
        )
        modules = {
            "comtypes": SimpleNamespace(CoInitializeEx=Mock(), CoUninitialize=Mock(), COINIT_MULTITHREADED=0),
            "pycaw": SimpleNamespace(),
            "pycaw.callbacks": SimpleNamespace(AudioSessionEvents=object, AudioSessionNotification=object, MMNotificationClient=object),
            "pycaw.constants": constants,
            "pycaw.pycaw": SimpleNamespace(AudioUtilities=utilities, AudioSession=lambda session: session, IAudioSessionControl2=object),
        }
        with patch.dict(sys.modules, modules), patch.object(monitor._refresh_event, "wait", side_effect=wait):
            monitor._run()
        self.assertEqual(len(calls), 2)
        applied.assert_called_once()
        self.assertTrue(first.unregistered and second.unregistered)
        self.assertTrue(manager1.unregistered and manager2.unregistered)
        endpoint_enumerator.UnregisterEndpointNotificationCallback.assert_called_once()
        self.assertFalse(monitor.is_ready)


if __name__ == "__main__":
    unittest.main()
