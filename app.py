"""Windows per-application volume manager."""

import argparse
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk

import psutil

from app_volume_manager.audio_backend import AudioBackendError, WindowsAudioBackend
from app_volume_manager.audio_monitor import DEVICES_CHANGED, AudioSessionMonitor, refresh_interval_ms
from app_volume_manager.color_utils import normalize_hex_color
from app_volume_manager.process_list import ProcessRow, build_process_rows, row_matches_search, row_values
from app_volume_manager.rules import AppRule
from app_volume_manager.selection import (
    TemporaryTargets,
    identify_processes,
    plan_apply,
    plan_removal,
    target_key,
)
from app_volume_manager.settings import PreferenceStore, SettingsError, SettingsStore, default_settings_path
from app_volume_manager.single_instance import SingleInstance
from app_volume_manager.startup import is_startup_enabled, migrate_startup, set_startup_enabled
from app_volume_manager.ui import APP_NAME
from app_volume_manager.ui.process_table import ProcessTable
from app_volume_manager.ui.rule_dialog import show_rule_dialog
from app_volume_manager.ui.slider_color_dialog import show_slider_color_dialog
from app_volume_manager.ui.theme import PALETTES, apply_base_theme, configure_scrollbars, configure_volume_slider
from app_volume_manager.ui.tray import start_tray_icon
from app_volume_manager.ui.volume_scale import allow_scale_thumb_click, percent
from app_volume_manager.ui.windows_shell import destroy_icon, set_app_user_model_id, set_window_icon
from app_volume_manager.volume_service import VolumeRuleEngine

AUDIO_EVENT_CHECK_MS = 100
DEFAULT_SLIDER_THUMB_COLOR = PreferenceStore.DEFAULT_SLIDER_THUMB_COLOR


def resource_path(relative_path: str) -> Path:
    """Find bundled resources both from source and from a PyInstaller build."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def configure_logging() -> None:
    """Keep a small log of warnings and errors next to the settings file."""
    log_path = default_settings_path().with_name("app.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=200_000, backupCount=1, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler])


class VolumeManagerApp:
    def __init__(self, root: tk.Tk, instance: SingleInstance, start_minimized: bool = False) -> None:
        self.root = root
        self.instance_guard = instance
        if start_minimized:
            self.root.withdraw()
        self.store = SettingsStore()
        self.preference_store = PreferenceStore()
        self.theme = "light"
        self.slider_thumb_color = DEFAULT_SLIDER_THUMB_COLOR
        self._native_icon_handle = None
        self.backend = WindowsAudioBackend()
        self.engine = VolumeRuleEngine()
        self.rules: list[AppRule] = []
        self.last_sessions = []
        self.checked_rows: set[str] = set()
        self._row_info: dict[str, ProcessRow] = {}
        self._all_row_info: dict[str, ProcessRow] = {}
        # Temporary PID-scoped targets are used only when Windows doesn't expose
        # enough stable role information to create a safe persistent profile.
        self.temporary = TemporaryTargets()
        self.tray_icon = None
        self._closing = False
        self.audio_ready = False
        self.window_icon = None
        self.window_visible = True
        self._poll_after_id = None
        self._audio_event_after_id = None
        self._audio_event_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._startup_busy = False
        self._startup_enabled = False
        self._startup_results: queue.SimpleQueue = queue.SimpleQueue()

        self.root.title(APP_NAME)
        self.root.geometry("1000x620")
        # Keep the window comfortably resizable while protecting the controls at
        # the bottom from being pushed off-screen by the process table.
        self.root.minsize(820, 460)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.bind("<Map>", self._on_visibility_event, add="+")
        self.root.bind("<Unmap>", self._on_visibility_event, add="+")
        startup_errors = []
        try:
            self.rules = self.store.load_rules()
        except SettingsError as exc:
            startup_errors.append(str(exc))

        # Protect audio before loading appearance assets or constructing the UI.
        try:
            self.backend.initialize()
            self.audio_ready = True
        except AudioBackendError as exc:
            startup_errors.append(str(exc))
        self.audio_monitor = AudioSessionMonitor(
            wrap_session=self.backend.wrap_notified_session,
            on_session_created=self._apply_notified_session,
            on_change=self._queue_audio_event,
        )
        self.audio_monitor.start()
        if self.audio_ready:
            try:
                self.last_sessions = self.backend.get_sessions()
                result = self.engine.scan(self.last_sessions, self.rules)
                startup_errors.extend(result.errors)
            except Exception as exc:
                startup_errors.append(f"Initial audio scan failed; will retry: {exc}")

        try:
            self.theme, self.slider_thumb_color = self.preference_store.load_preferences()
        except SettingsError as exc:
            startup_errors.append(str(exc))
            self.theme = "light"
            self.slider_thumb_color = DEFAULT_SLIDER_THUMB_COLOR

        self._set_window_icon()
        self._apply_theme(self.theme)
        self._build_ui()

        self._start_startup_update(None)

        self._start_tray_icon()
        if start_minimized and self.tray_icon is not None:
            self.window_visible = False
        elif start_minimized:
            self.root.deiconify()  # Keep the app reachable if tray setup fails.
        self._audio_event_after_id = self.root.after(
            AUDIO_EVENT_CHECK_MS, self._process_audio_events
        )
        self._schedule_poll(300)
        if startup_errors:
            self.status_var.set(startup_errors[0])
            if not start_minimized:
                self.root.after(0, lambda: messagebox.showwarning(APP_NAME, "\n\n".join(startup_errors)))

    def _set_window_icon(self) -> None:
        icon_path = resource_path("assets/app-icon.ico")
        try:
            # Set the actual toplevel icon, not just Tk's default child-window icon.
            self.root.iconbitmap(str(icon_path))
        except (OSError, tk.TclError):
            pass
        try:
            self.window_icon = tk.PhotoImage(file=str(resource_path("assets/app-icon.png")))
            self.root.iconphoto(True, self.window_icon)
        except (OSError, tk.TclError):
            self.window_icon = None

        # When launched from source, Windows otherwise may use pythonw.exe's icon
        # for the taskbar button. An explicit WM_SETICON sets the window icon directly.
        if sys.platform == "win32":
            try:
                self.root.update_idletasks()
                self._native_icon_handle = set_window_icon(self.root.winfo_id(), icon_path)
            except (AttributeError, OSError, tk.TclError):
                # Tk's own icon APIs remain as a fallback.
                pass

    def _apply_theme(self, theme: str) -> None:
        """Apply a small, consistent light or dark palette to the Tk UI."""
        self.theme = theme if theme in PALETTES else "light"
        self.style, self.colors = apply_base_theme(self.root, self.theme)
        self._configure_volume_slider_style()
        self._configure_scrollbar_styles()

    def _configure_scrollbar_styles(self) -> None:
        configure_scrollbars(self.style, self.colors, self.slider_thumb_color)

    def _configure_volume_slider_style(self) -> None:
        configure_volume_slider(self.style, self.colors, self.slider_thumb_color)

    def _set_slider_thumb_color(self, color: str) -> None:
        """Update the visible slider; persistence is handled separately."""
        self.slider_thumb_color = normalize_hex_color(color)
        self._configure_volume_slider_style()
        self._configure_scrollbar_styles()

    def change_theme(self, _event=None) -> None:
        requested = self.theme_var.get().casefold()
        try:
            self.preference_store.save_theme(requested)
        except SettingsError as exc:
            self.theme_var.set(self.theme.title())
            messagebox.showerror(APP_NAME, f"Could not save appearance preference:\n{exc}")
            return
        self._apply_theme(requested)
        self.status_var.set(f"{requested.title()} appearance saved.")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        # Grid gives the process table the only expandable row. Unlike a long
        # pack() chain, a short window compresses the table instead of letting
        # its requested 14-row height push the volume/actions/settings off-screen.
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        heading = ttk.Frame(outer)
        heading.grid(row=0, column=0, sticky="ew")
        ttk.Label(heading, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(side="left")
        heading_actions = ttk.Frame(heading)
        heading_actions.pack(side="right")
        ttk.Label(heading_actions, text="Appearance").pack(side="left", padx=(0, 6))
        self.theme_var = tk.StringVar(value=self.theme.title())
        theme_picker = ttk.Combobox(
            heading_actions, textvariable=self.theme_var, values=("Light", "Dark"),
            state="readonly", width=8,
        )
        theme_picker.pack(side="left", padx=(0, 10))
        theme_picker.bind("<<ComboboxSelected>>", self.change_theme)
        ttk.Button(heading_actions, text="Refresh list", command=self.refresh_list).pack(side="left")

        description = ttk.Label(
            outer,
            text=(
                "Lists running processes with audio. Audio sessions counts the separate Windows "
                "sessions owned by each process; a rule adjusts each session. Saved rules apply "
                "when matching sessions appear."
            ),
            justify="left",
        )
        description.grid(row=1, column=0, sticky="ew", pady=(4, 6))
        description.bind("<Configure>", lambda event: description.configure(wraplength=event.width))

        search_frame = ttk.Frame(outer)
        search_frame.grid(row=2, column=0, sticky="ew", pady=(0, 7))
        search_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="Search processes").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(
            search_frame, textvariable=self.search_var, width=32
        )
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<Escape>", self._clear_process_search)
        ttk.Button(
            search_frame, text="Clear", command=self._clear_process_search, padding=(7, 4)
        ).grid(row=0, column=2, padx=(6, 12))
        self.search_summary_var = tk.StringVar(value="0 processes")
        ttk.Label(
            search_frame, textvariable=self.search_summary_var, anchor="e"
        ).grid(row=0, column=3, sticky="e")
        self.search_var.trace_add("write", lambda *_args: self._refresh_table())

        self.process_table = ProcessTable(outer, self._on_table_click)
        self.process_table.frame.grid(row=3, column=0, sticky="nsew")
        self.table = self.process_table.tree
        self.table_frame = self.process_table.frame

        volume_frame = ttk.Frame(outer)
        volume_frame.grid(row=4, column=0, sticky="ew", pady=(10, 4))
        volume_frame.grid_columnconfigure(1, weight=1)
        self.target_volume_var = tk.DoubleVar(value=50)
        self.target_volume_label = tk.StringVar(value="Volume for selected: 50%")
        ttk.Label(volume_frame, textvariable=self.target_volume_label).grid(
            row=0, column=0, sticky="w"
        )
        self.volume_scale = ttk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.target_volume_var,
            command=self._update_target_label,
            length=180,
            takefocus=True,
            style="Volume.Horizontal.TScale",
        )
        self.volume_scale.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.volume_scale.bind("<Button-1>", allow_scale_thumb_click)
        self.volume_scale.state(["disabled"])
        ttk.Button(
            volume_frame, text="Slider color…", command=self.edit_slider_thumb_color
        ).grid(row=0, column=2, sticky="e", padx=(10, 0))

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, sticky="ew", pady=(5, 6))
        actions.grid_columnconfigure(4, weight=1)
        ttk.Button(actions, text="Add rule for app…", command=self.add_rule).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(actions, text="Apply to selected", command=self.apply_to_selected).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        ttk.Button(actions, text="Remove selected", command=self.remove_selected).grid(
            row=0, column=2, sticky="w", padx=(6, 0)
        )
        ttk.Button(actions, text="Reapply saved volumes", command=self.reapply_now).grid(
            row=0, column=3, sticky="w", padx=(6, 0)
        )
        ttk.Button(actions, text="Settings folder", command=self.open_settings_folder).grid(
            row=0, column=5, sticky="e", padx=(8, 0)
        )

        footer = ttk.Frame(outer)
        footer.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        footer.grid_columnconfigure(1, weight=1)
        startup_controls = ttk.Frame(footer)
        startup_controls.grid(row=0, column=0, sticky="w")
        self.startup_var = tk.BooleanVar(value=False)
        self.startup_checkbutton = ttk.Checkbutton(
            startup_controls,
            text="Start with Windows",
            variable=self.startup_var,
            command=self.change_startup,
        )
        self.startup_checkbutton.grid(row=0, column=0, sticky="w")
        self.startup_status_var = tk.StringVar(value="Not enabled")
        ttk.Label(
            startup_controls,
            textvariable=self.startup_status_var,
            anchor="w",
            padding=(0, 1),
        ).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        self.status_var = tk.StringVar(value="Searching for Windows audio sessions…")
        self.status_label = ttk.Label(
            footer, textvariable=self.status_var, wraplength=560, justify="right", anchor="e"
        )
        self.status_label.grid(
            row=0, column=1, sticky="e", padx=(12, 0)
        )
        self.root.bind("<Configure>", self._on_root_resize, add="+")
        self._refresh_table()
        self.root.after_idle(self.process_table.fit_columns)

    def _on_root_resize(self, event) -> None:
        """Adapt the status line to the available footer width during resizing."""
        if event.widget is not self.root:
            return
        available = max(180, self.root.winfo_width() - 390)
        self.status_label.configure(wraplength=min(560, available))

    def _start_tray_icon(self) -> None:
        try:
            self.tray_icon = start_tray_icon(
                APP_NAME,
                resource_path("assets/app-icon.png"),
                self._tray_show,
                self._tray_reapply,
                self._tray_exit,
            )
        except Exception as exc:
            # The main window still works if the tray library can't initialize.
            self.tray_icon = None
            self.status_var.set(f"System tray unavailable: {exc}")

    def _tray_show(self, _icon, _item) -> None:
        self.root.after(0, self.show_window)

    def _tray_reapply(self, _icon, _item) -> None:
        self.root.after(0, self.reapply_now)

    def _tray_exit(self, _icon, _item) -> None:
        self.root.after(0, self.close)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.window_visible = True
        self._scan_sessions(update_table=True)
        self._reschedule_poll()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def hide_to_tray(self) -> None:
        if self.tray_icon is None:
            self.close()
            return
        self.root.withdraw()
        self.window_visible = False
        self._reschedule_poll()

    def _on_visibility_event(self, event) -> None:
        # Bindings on the toplevel also receive its child widgets' Map/Unmap events.
        if event.widget is self.root and not self._closing:
            self.root.after_idle(self._sync_window_visibility)

    def _sync_window_visibility(self) -> None:
        if self._closing:
            return
        visible = self.root.state() == "normal"
        if visible == self.window_visible:
            return
        self.window_visible = visible
        if visible:
            # On restore, refresh immediately rather than waiting for the next timer.
            self._scan_sessions(update_table=True)
        self._reschedule_poll()

    def _queue_audio_event(self, kind: str) -> None:
        if not self._closing:
            self._audio_event_queue.put(kind)

    def _apply_notified_session(self, session) -> None:
        """Apply a persistent rule on the Core Audio callback thread immediately."""
        if self._closing:
            return
        self.engine.apply_new_session(
            session, tuple(self.rules), temporary_targets=self.temporary.live()
        )
        # AudioSessionMonitor queues the GUI refresh after this callback returns.
        # COM session objects themselves never cross from the callback thread to Tk.

    def _on_table_click(self, event) -> str | None:
        # Treat clicking any cell in a process row as selecting that process,
        # not just clicking the small checkbox glyph in the first column.
        region = self.table.identify_region(event.x, event.y)
        if region not in {"cell", "tree"}:
            return None
        row_id = self.table.identify_row(event.y)
        if not row_id or row_id not in self._row_info:
            return None
        if row_id in self.checked_rows:
            self.checked_rows.remove(row_id)
        else:
            self.checked_rows.add(row_id)
        self._refresh_table()
        # Returning "break" skips the default binding, so highlight the row here.
        self.table.selection_set(row_id)
        self.table.focus(row_id)
        return "break"

    def _clear_process_search(self, _event=None) -> str:
        """Clear the process filter and return focus to the search field."""
        self.search_var.set("")
        self.search_entry.focus_set()
        return "break"

    def _update_target_label(self, value: str) -> None:
        self.target_volume_label.set(f"Volume for selected: {percent(value)}%")

    def edit_slider_thumb_color(self) -> None:
        show_slider_color_dialog(
            self.root,
            self.slider_thumb_color,
            self.preference_store,
            self._set_slider_thumb_color,
            self.status_var,
        )

    def _selected_rows(self) -> list[ProcessRow]:
        return [self._all_row_info[row_id] for row_id in self.checked_rows if row_id in self._all_row_info]

    def apply_to_selected(self) -> None:
        selected = self._selected_rows()
        if not selected:
            messagebox.showinfo(APP_NAME, "Tick one or more rows in the Select column first.")
            return

        target = percent(self.target_volume_var.get())

        def confirm_profile(row: ProcessRow, matching_count: int) -> bool:
            return messagebox.askyesno(
                APP_NAME,
                f"{row.executable} has {matching_count} running processes with the same profile. "
                "Saving this rule will affect all of them, including unchecked processes, "
                "and matching processes started later.\n\n"
                "Yes: save for this profile.\n"
                "No: apply only to checked processes until they exit.",
            )

        plan = plan_apply(selected, self._all_row_info, self.rules, target, confirm_profile)
        try:
            processes = identify_processes(plan.temporary_keys)
        except psutil.Error as exc:
            messagebox.showerror(
                APP_NAME,
                f"Could not identify the selected process. Refresh the list and try again.\n\n{exc}",
            )
            return

        persistent_count = plan.persistent_count
        temporary_count = len(plan.temporary_keys)
        if persistent_count:
            try:
                self.store.save_rules(plan.rules)
            except SettingsError as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return
            self.rules = plan.rules

        self.temporary.discard(plan.superseded_keys)
        for key, process in processes.items():
            self.temporary.add(key, target, process)

        if persistent_count or temporary_count:
            self._scan_sessions(force=True)
        if persistent_count and temporary_count:
            self.status_var.set(
                f"Saved {persistent_count} rule(s); applied temporarily to "
                f"{temporary_count} selected process instance(s) that can't be matched safely after restart."
            )
        elif persistent_count:
            self.status_var.set(
                f"Saved {persistent_count} rule(s). Process profiles match the same executable profile "
                "after restart; app rules affect every matching process."
            )
        elif temporary_count:
            self.status_var.set(
                f"Applied {target}% to {temporary_count} checked process instance(s) for this run only. "
                "Use Add rule for app for a persistent rule when a process profile can't be identified."
            )
        self._refresh_table()

    def remove_selected(self) -> None:
        selected = self._selected_rows()
        if not selected:
            messagebox.showinfo(APP_NAME, "Tick one or more rows in the Select column first.")
            return

        plan = plan_removal(selected, self.temporary)
        if plan.is_empty:
            messagebox.showinfo(APP_NAME, "The selected process(es) have no volume rule or temporary target to remove.")
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Remove these volume rules and temporary targets?\n\n" + "\n".join(plan.descriptions()),
        ):
            return

        remove_keys = {rule.key for rule in plan.rules}
        new_rules = [rule for rule in self.rules if rule.key not in remove_keys]
        if remove_keys:
            try:
                self.store.save_rules(new_rules)
            except SettingsError as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return

        self.rules = new_rules
        self.temporary.discard(plan.temporary_keys)
        self._refresh_table()
        self.status_var.set(
            f"Removed {len(remove_keys)} saved rule(s) and {len(plan.temporary_keys)} temporary target(s). "
            "Current volumes are not reset."
        )

    def add_rule(self) -> None:
        show_rule_dialog(
            self.root,
            sorted({session.executable for session in self.last_sessions}, key=str.casefold),
            int(self.target_volume_var.get()),
            self._save_app_rule,
        )

    def _save_app_rule(self, rule: AppRule) -> None:
        new_rules = [existing for existing in self.rules if existing.key != rule.key]
        new_rules.append(rule)
        new_rules.sort(key=lambda existing: existing.executable.casefold())
        self.store.save_rules(new_rules)
        self.rules = new_rules
        self._scan_sessions(force=True)
        self.status_var.set(f"Saved {rule.executable}; waiting for its audio session if it isn't active.")

    def _update_startup_status(self) -> None:
        self.startup_status_var.set(
            "Starts when you sign in" if self.startup_var.get() else "Not enabled"
        )

    def change_startup(self) -> None:
        self._start_startup_update(bool(self.startup_var.get()))

    def _start_startup_update(self, requested: bool | None) -> None:
        if self._startup_busy:
            return
        self._startup_busy = True
        self.startup_checkbutton.state(["disabled"])
        self.startup_status_var.set("Checking…" if requested is None else "Updating…")

        def update() -> None:
            try:
                if requested is None:
                    migrate_startup()
                    enabled = is_startup_enabled()
                else:
                    set_startup_enabled(requested)
                    enabled = requested
                self._startup_results.put((enabled, None))
            except Exception as exc:
                self._startup_results.put((None, str(exc)))

        threading.Thread(target=update, name="startup-setting", daemon=True).start()

    def _process_startup_results(self) -> None:
        try:
            enabled, error = self._startup_results.get_nowait()
        except queue.Empty:
            return
        self._startup_busy = False
        self.startup_checkbutton.state(["!disabled"])
        if error is None:
            self._startup_enabled = enabled
        self.startup_var.set(self._startup_enabled)
        self._update_startup_status()
        if error is not None:
            self.status_var.set(f"Windows startup setting failed: {error}")
            if self.window_visible:
                messagebox.showerror(APP_NAME, f"Could not update Windows startup setting:\n{error}")

    def open_settings_folder(self) -> None:
        path = self.store.path.parent
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]  # Windows-only app
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open settings folder:\n{exc}")

    def reapply_now(self) -> None:
        self._scan_sessions(force=True)

    def _schedule_poll(self, delay_ms: int) -> None:
        if self._closing:
            return
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
        self._poll_after_id = self.root.after(max(0, delay_ms), self._poll_sessions)

    def _reschedule_poll(self) -> None:
        self._schedule_poll(refresh_interval_ms(self.window_visible, self.audio_monitor.healthy))

    def _poll_sessions(self) -> None:
        self._poll_after_id = None
        if self._closing:
            return
        # In the tray, new sessions are handled by Core Audio events. A 60-second
        # safety sweep catches missed notifications; if events cannot be registered,
        # fall back to 5-second polling so automation still works.
        if not (self.window_visible and self.audio_monitor.healthy):
            self.backend.invalidate_devices()
        self._scan_sessions(update_table=self.window_visible)
        self._reschedule_poll()

    def _process_audio_events(self) -> None:
        self._audio_event_after_id = None
        if self._closing:
            return
        self._process_startup_results()
        if self.instance_guard.show_requested():
            self.show_window()
        kinds = set()
        while True:
            try:
                kinds.add(self._audio_event_queue.get_nowait())
            except queue.Empty:
                break
        if kinds:
            if DEVICES_CHANGED in kinds:
                self.backend.invalidate_devices()
            self._scan_sessions(update_table=self.window_visible)
            self._reschedule_poll()
        if not self._closing:
            self._audio_event_after_id = self.root.after(
                AUDIO_EVENT_CHECK_MS, self._process_audio_events
            )

    def refresh_list(self) -> None:
        self.backend.invalidate_devices()
        self._scan_sessions()

    def _scan_sessions(
        self, force: bool = False, update_table: bool | None = None
    ) -> None:
        if self._closing:
            return
        if update_table is None:
            update_table = self.window_visible
        if not self.audio_ready:
            try:
                self.backend.initialize()
                self.audio_ready = True
            except AudioBackendError as exc:
                self.status_var.set(f"Audio monitoring unavailable; retrying: {exc}")
                if update_table:
                    self._refresh_table()
                return
        try:
            self.last_sessions = self.backend.get_sessions()
            result = self.engine.scan(
                self.last_sessions,
                self.rules,
                force=force,
                temporary_targets=self.temporary.prune(),
            )
            process_count = len({
                (session.executable.casefold(), session.process_id)
                for session in self.last_sessions
            })
            if result.errors:
                self.status_var.set(
                    f"Could not set {len(result.errors)} audio session(s); will retry automatically."
                )
            elif result.applied_count:
                self.status_var.set(
                    f"Applied {result.applied_count} volume rule(s). Found {process_count} process(es) with audio."
                )
            elif not self.last_sessions:
                self.status_var.set(
                    "No active audio sessions found. Start an app and play audio; this list refreshes automatically."
                )
            else:
                self.status_var.set(
                    f"Found {process_count} process(es) with audio across {len(self.last_sessions)} session(s)."
                )
            warnings = self.backend.last_warnings
            if warnings and not result.errors:
                self.status_var.set(
                    f"Found {process_count} process(es) with audio; {len(warnings)} device warning(s). "
                    "Some non-default outputs may be missing."
                )
        except Exception as exc:
            self.status_var.set(f"Audio scan failed; will retry: {exc}")
        if update_table:
            self._refresh_table()

    def _row_values(self, row: ProcessRow) -> tuple[str, ...]:
        temporary_target = self.temporary.get(target_key(row)) if row.active and row.process_id is not None else None
        return row_values(row, row.row_id in self.checked_rows, temporary_target)

    def _refresh_table(self) -> None:
        all_rows = build_process_rows(self.last_sessions, self.rules)
        self._all_row_info = {row.row_id: row for row in all_rows}
        # Filtering changes only which rows are drawn. Checked processes stay
        # checked while hidden by a query, and can still be acted on safely.
        self.checked_rows.intersection_update(self._all_row_info)
        rows = [row for row in all_rows if row_matches_search(row, self.search_var.get().strip())]
        self._row_info = {row.row_id: row for row in rows}
        self.search_summary_var.set(f"{len(rows)} shown  ·  {len(self.checked_rows)} selected")

        if rows:
            shown = {row.row_id: self._row_values(row) for row in rows}
        elif all_rows:
            shown = {"no-search-matches": (
                "—", "No matching processes", "—", "—", "—", "—", "—",
                "Clear the search to see all processes",
            )}
        else:
            shown = {"no-audio-sessions": (
                "—", "No audio sessions", "—", "0", "—", "—", "—",
                "Play sound in an app, then refresh",
            )}

        self.process_table.show(shown, self._row_info)
        self._sync_volume_scale_enabled()

    def _sync_volume_scale_enabled(self) -> None:
        """Only allow volume adjustments when at least one process is checked."""
        has_selection = bool(self._selected_rows())
        self.volume_scale.state(["!disabled"] if has_selection else ["disabled"])
        if has_selection:
            self.target_volume_label.set(f"Volume for selected: {percent(self.target_volume_var.get())}%")
        else:
            self.target_volume_label.set("Select a process to change volume")

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for callback_id in (self._poll_after_id, self._audio_event_after_id):
            if callback_id is not None:
                self.root.after_cancel(callback_id)
        self.audio_monitor.stop()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.backend.shutdown()
        self.root.destroy()
        if self._native_icon_handle:
            destroy_icon(self._native_icon_handle)
            self._native_icon_handle = None



def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--minimized", action="store_true", help="Start hidden in the system tray")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("App Volume Manager is a Windows-only application.", file=sys.stderr)
        return 1
    instance = SingleInstance()
    try:
        if not instance.acquire(show_existing=not args.minimized):
            return 0
        configure_logging()
        set_app_user_model_id()
        root = tk.Tk()
        VolumeManagerApp(root, instance, start_minimized=args.minimized)
        root.mainloop()
        return 0
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
