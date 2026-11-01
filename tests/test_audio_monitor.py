import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app_volume_manager.audio_monitor import (
    DEVICES_CHANGED, SESSIONS_CHANGED, AudioSessionMonitor, refresh_interval_ms,
)
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
        changed.assert_called_once_with(SESSIONS_CHANGED)

    def test_visible_and_hidden_refresh_intervals(self):
        self.assertEqual(refresh_interval_ms(True, True), 2_000)
        self.assertEqual(refresh_interval_ms(True, False), 2_000)
        self.assertEqual(refresh_interval_ms(False, True), 60_000)
        self.assertEqual(refresh_interval_ms(False, False), 5_000)

    def test_healthy_needs_a_ready_monitor_without_errors(self):
        monitor = AudioSessionMonitor(Mock(), Mock(), Mock())
        self.assertFalse(monitor.healthy)
        monitor._set_status(True, None)
        self.assertTrue(monitor.healthy)
        monitor._set_status(True, "Device notifications unavailable")
        self.assertFalse(monitor.healthy)


class _Session:
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


class _Manager:
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


class NotificationLifecycleTests(unittest.TestCase):
    def run_monitor(self, devices, endpoint_enumerator, changed, applied, on_wait):
        """Run one monitor pass per on_wait call; on_wait(n) returns the wait() result."""
        monitor = AudioSessionMonitor(
            wrap_session=lambda raw, *_args: AudioSession("Discord.exe", raw.InstanceIdentifier, lambda _: None),
            on_session_created=applied,
            on_change=changed,
        )
        device_queries = []

        def get_all_devices(**_kwargs):
            device_queries.append(True)
            return devices

        constants = SimpleNamespace(
            DEVICE_STATE=SimpleNamespace(ACTIVE=SimpleNamespace(value=1)),
            EDataFlow=SimpleNamespace(eRender=SimpleNamespace(value=0)),
        )
        utilities = SimpleNamespace(
            GetDeviceEnumerator=lambda: endpoint_enumerator,
            GetAllDevices=get_all_devices,
        )
        modules = {
            "comtypes": SimpleNamespace(CoInitializeEx=Mock(), CoUninitialize=Mock(), COINIT_MULTITHREADED=0),
            "pycaw": SimpleNamespace(),
            "pycaw.callbacks": SimpleNamespace(
                AudioSessionEvents=object, AudioSessionNotification=object, MMNotificationClient=object,
            ),
            "pycaw.constants": constants,
            "pycaw.pycaw": SimpleNamespace(
                AudioUtilities=utilities, AudioSession=lambda session: session, IAudioSessionControl2=object,
            ),
        }
        waits = []

        def wait(_interval):
            waits.append(True)
            result = on_wait(len(waits), monitor)
            if len(waits) == 2:
                monitor._stop_event.set()
            return result

        with patch.dict(sys.modules, modules), patch.object(monitor._refresh_event, "wait", side_effect=wait):
            monitor._run()
        return monitor, device_queries

    def test_volume_changes_wake_scan_and_device_change_registers_new_output(self):
        first, second = _Session("one"), _Session("two")
        manager1, manager2 = _Manager(first), _Manager(second)
        devices = [SimpleNamespace(id="speakers", AudioSessionManager=manager1)]
        endpoint_enumerator = Mock()
        changed, applied = Mock(), Mock()

        def on_wait(call, monitor):
            if call == 1:
                before = changed.call_count
                first.callback.on_simple_volume_changed(1.0, 0, None)
                self.assertGreater(changed.call_count, before)
                devices.append(SimpleNamespace(id="headset", AudioSessionManager=manager2))
                endpoint_enumerator.RegisterEndpointNotificationCallback.call_args.args[0].on_device_added("headset")
                self.assertTrue(monitor._refresh_event.is_set())
                manager1.callback.on_session_created(_Session("new-voice"))
            return True

        monitor, device_queries = self.run_monitor(devices, endpoint_enumerator, changed, applied, on_wait)
        applied.assert_called_once()
        self.assertTrue(first.unregistered and second.unregistered)
        self.assertTrue(manager1.unregistered and manager2.unregistered)
        endpoint_enumerator.UnregisterEndpointNotificationCallback.assert_called_once()
        self.assertFalse(monitor.is_ready)
        self.assertEqual(len(device_queries), 2)
        self.assertIn(DEVICES_CHANGED, [call.args[0] for call in changed.call_args_list])

    def test_session_events_do_not_enumerate_devices_again_but_the_timeout_does(self):
        session = _Session("one")
        devices = [SimpleNamespace(id="speakers", AudioSessionManager=_Manager(session))]
        for timed_out, expected_queries in ((False, 1), (True, 2)):
            with self.subTest(timed_out=timed_out):
                changed = Mock()

                def on_wait(call, _monitor):
                    if call == 1:
                        session.callback.on_state_changed(0, "inactive")
                    return not timed_out

                _monitor, device_queries = self.run_monitor(devices, Mock(), changed, Mock(), on_wait)
                self.assertEqual(len(device_queries), expected_queries)
                self.assertIn(SESSIONS_CHANGED, [call.args[0] for call in changed.call_args_list])


if __name__ == "__main__":
    unittest.main()
