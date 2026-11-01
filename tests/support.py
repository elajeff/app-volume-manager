"""Build a real main window with fake Windows collaborators for the GUI tests."""

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from app_volume_manager.settings import PreferenceStore
from app_volume_manager.ui.main_window import VolumeManagerApp


class FakeBackend:
    def __init__(self, sessions=()):
        self.sessions = list(sessions)
        self.last_warnings = []
        self.invalidated = 0

    def initialize(self):
        pass

    def get_sessions(self):
        return list(self.sessions)

    def invalidate_devices(self):
        self.invalidated += 1

    def wrap_notified_session(self, *_args):
        return None

    def shutdown(self):
        pass


class FakeRuleStore:
    def __init__(self, rules=()):
        self.rules = list(rules)
        self.saved = []
        self.error = None
        self.path = Path("settings.json")

    def load_rules(self):
        return list(self.rules)

    def save_rules(self, rules):
        if self.error is not None:
            raise self.error
        self.saved.append(list(rules))
        self.rules = list(rules)


class FakePreferenceStore:
    def __init__(self, theme="light", color=PreferenceStore.DEFAULT_SLIDER_THUMB_COLOR):
        self.theme = theme
        self.color = color
        self.saved_colors = []

    def load_preferences(self):
        return self.theme, self.color

    def save_theme(self, theme):
        self.theme = theme

    def save_slider_thumb_color(self, color):
        self.saved_colors.append(color)
        self.color = color


def fake_startup(**overrides):
    functions = {
        "check_startup": lambda: False,
        "set_startup_enabled": lambda _enabled: None,
    }
    functions.update(overrides)
    return SimpleNamespace(**functions)


def open_window(test, sessions=(), rules=(), start_minimized=False, **overrides):
    """Create the window on a real Tk root and close it when the test ends.

    Skips the test when no display is available. Keyword arguments replace the
    default fakes (backend, store, preference_store, monitor_factory,
    tray_factory, startup).
    """
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        test.skipTest(f"Tk display is not available in this environment: {exc}")
    options = {
        "backend": FakeBackend(sessions),
        "store": FakeRuleStore(rules),
        "preference_store": FakePreferenceStore(),
        "monitor_factory": lambda **_callbacks: Mock(healthy=True),
        "tray_factory": Mock(),
        "startup": fake_startup(),
    }
    options.update(overrides)
    instance = Mock(show_requested=Mock(return_value=False))
    try:
        app = VolumeManagerApp(root, instance, start_minimized, **options)
    except BaseException:
        root.destroy()
        raise
    test.addCleanup(close_window, app)
    return app


def close_window(app):
    """Close a test window; pending idle callbacks run first so they do not outlive it."""
    try:
        app.root.update_idletasks()
    except tk.TclError:
        pass
    app.close()
