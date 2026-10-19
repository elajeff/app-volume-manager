"""Windows per-application volume manager."""

import argparse
import ctypes
import os
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_volume_manager.audio_backend import AudioBackendError, WindowsAudioBackend
from app_volume_manager.audio_monitor import AudioSessionMonitor, refresh_interval_ms
from app_volume_manager.color_utils import normalize_hex_color
from app_volume_manager.process_list import ProcessRow, build_process_rows
from app_volume_manager.rules import AppRule
from app_volume_manager.settings import PreferenceStore, SettingsError, SettingsStore
from app_volume_manager.slider_color_dialog import show_slider_color_dialog
from app_volume_manager.startup import is_startup_enabled, set_startup_enabled
from app_volume_manager.volume_service import VolumeRuleEngine

APP_NAME = "App Volume Manager"
APP_USER_MODEL_ID = "AppVolumeManager.Desktop"
AUDIO_EVENT_CHECK_MS = 100
DEFAULT_SLIDER_THUMB_COLOR = PreferenceStore.DEFAULT_SLIDER_THUMB_COLOR


def resource_path(relative_path: str) -> Path:
    """Find bundled resources both from source and from a PyInstaller build."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def set_windows_app_identity() -> None:
    """Give the source-run app its own Windows taskbar identity instead of Python's."""
    if sys.platform != "win32":
        return
    try:
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        setter(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        # The explicit window icon below still provides a fallback.
        pass


def allow_scale_thumb_click(event) -> str | None:
    """Allow mouse interaction only when the pointer is on the scale thumb.

    Returning ``break`` for clicks on the trough prevents ttk.Scale's default
    behavior of jumping to the clicked position. Native arrow-key handling is
    unaffected, and clicks/drags that begin on the thumb keep the default binding.
    """
    try:
        element = str(event.widget.identify(event.x, event.y)).casefold()
    except (AttributeError, tk.TclError):
        return "break"
    if "slider" in element or "thumb" in element:
        return None
    return "break"


class VolumeManagerApp:
    def __init__(self, root: tk.Tk, start_minimized: bool = False) -> None:
        self.root = root
        self.store = SettingsStore()
        self.preference_store = PreferenceStore()
        self.theme = "light"
        self.slider_thumb_color = DEFAULT_SLIDER_THUMB_COLOR
        self.style = None
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
        self.temporary_process_targets: dict[tuple[int, str], int] = {}
        self.tray_icon = None
        self._closing = False
        self.audio_ready = False
        self.window_icon = None
        self.window_visible = True
        self._poll_after_id = None
        self._audio_event_after_id = None
        self._audio_event_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.audio_monitor: AudioSessionMonitor | None = None

        self.root.title(APP_NAME)
        self.root.geometry("1000x620")
        # Keep the window comfortably resizable while protecting the controls at
        # the bottom from being pushed off-screen by the process table.
        self.root.minsize(820, 460)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.root.bind("<Map>", self._on_visibility_event, add="+")
        self.root.bind("<Unmap>", self._on_visibility_event, add="+")
        self._set_window_icon()

        try:
            self.rules = self.store.load_rules()
        except SettingsError as exc:
            messagebox.showwarning(
                APP_NAME,
                "Saved volume rules could not be loaded. No rules will be applied until they are fixed.\n\n"
                f"{exc}",
            )

        try:
            self.theme, self.slider_thumb_color = self.preference_store.load_preferences()
        except SettingsError as exc:
            messagebox.showwarning(
                APP_NAME,
                "Appearance preferences could not be loaded. Light mode and the default blue "
                "slider will be used.\n\n" f"{exc}",
            )
            self.theme = "light"
            self.slider_thumb_color = DEFAULT_SLIDER_THUMB_COLOR

        self._apply_theme(self.theme)
        self._build_ui()

        try:
            self.backend.initialize()
            self.audio_ready = True
        except AudioBackendError as exc:
            self.status_var.set(str(exc))

        try:
            self.startup_var.set(is_startup_enabled())
        except OSError:
            self.startup_var.set(False)
        self._update_startup_status()

        self._start_tray_icon()
        self.audio_monitor = AudioSessionMonitor(
            wrap_session=self.backend.wrap_notified_session,
            on_session_created=self._apply_notified_session,
            on_change=self._queue_audio_event,
        )
        self.audio_monitor.start()
        self._audio_event_after_id = self.root.after(
            AUDIO_EVENT_CHECK_MS, self._process_audio_events
        )
        if start_minimized and self.tray_icon is not None:
            self.root.withdraw()
            self.window_visible = False
        self._schedule_poll(300)

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
        # for the taskbar button. Explicit WM_SETICON messages set both window sizes.
        if sys.platform == "win32":
            try:
                self.root.update_idletasks()
                user32 = ctypes.windll.user32
                user32.LoadImageW.argtypes = [
                    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                ]
                user32.LoadImageW.restype = ctypes.c_void_p
                handle = user32.LoadImageW(None, str(icon_path), 1, 0, 0, 0x0010)
                if handle:
                    user32.SendMessageW.argtypes = [
                        ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                    ]
                    user32.SendMessageW.restype = ctypes.c_ssize_t
                    hwnd = ctypes.c_void_p(self.root.winfo_id())
                    icon_handle = ctypes.c_void_p(handle)
                    user32.SendMessageW(hwnd, 0x0080, ctypes.c_void_p(0), icon_handle)  # ICON_SMALL
                    user32.SendMessageW(hwnd, 0x0080, ctypes.c_void_p(1), icon_handle)  # ICON_BIG
                    self._native_icon_handle = int(handle)
            except (AttributeError, OSError, tk.TclError):
                # Tk's own icon APIs remain as a fallback.
                pass

    def _apply_theme(self, theme: str) -> None:
        """Apply a small, consistent light or dark palette to the Tk UI."""
        self.theme = theme if theme in {"light", "dark"} else "light"
        if not hasattr(self, "slider_thumb_color"):
            self.slider_thumb_color = DEFAULT_SLIDER_THUMB_COLOR
        palettes = {
            "light": {
                "background": "#f3f5f8", "panel": "#ffffff", "text": "#202938",
                "muted": "#5d6878", "field": "#ffffff", "border": "#d4dce7",
                "selected": "#d8e8ff", "heading": "#e8edf4", "accent": "#356cc4",
                "trough": "#d9e0e9",
            },
            "dark": {
                "background": "#171a21", "panel": "#222733", "text": "#e8edf5",
                "muted": "#b1bbcb", "field": "#1c212b", "border": "#3b4555",
                "selected": "#344c70", "heading": "#2b3240", "accent": "#8ab4f8",
                "trough": "#3b4555",
            },
        }
        colors = palettes[self.theme]
        self.root.configure(background=colors["background"])
        self.style = ttk.Style(self.root)
        try:
            if "clam" in self.style.theme_names():
                self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure(
            ".", font=("Segoe UI", 9), background=colors["background"],
            foreground=colors["text"],
        )
        self.style.configure("TFrame", background=colors["background"])
        self.style.configure("TLabel", background=colors["background"], foreground=colors["text"])
        self.style.configure(
            "TButton", padding=(10, 5), background=colors["panel"],
            foreground=colors["text"], bordercolor=colors["border"],
        )
        self.style.map(
            "TButton",
            background=[("disabled", colors["background"]), ("active", colors["heading"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure("TCheckbutton", background=colors["background"], foreground=colors["text"])
        self.style.map("TCheckbutton", background=[("active", colors["background"])])
        self.style.configure(
            "TEntry", fieldbackground=colors["field"], foreground=colors["text"],
            bordercolor=colors["border"],
        )
        self.style.configure(
            "TCombobox", fieldbackground=colors["field"], background=colors["panel"],
            foreground=colors["text"], arrowcolor=colors["text"],
            bordercolor=colors["border"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", colors["field"])],
            foreground=[("readonly", colors["text"])],
            selectbackground=[("readonly", colors["field"])],
            selectforeground=[("readonly", colors["text"])],
        )
        self.style.configure(
            "Treeview", background=colors["field"], fieldbackground=colors["field"],
            foreground=colors["text"], rowheight=27, bordercolor=colors["border"],
        )
        self.style.map(
            "Treeview", background=[("selected", colors["selected"])],
            foreground=[("selected", colors["text"])],
        )
        self.style.configure(
            "Treeview.Heading", background=colors["heading"], foreground=colors["text"],
            relief="flat", padding=(6, 6),
        )
        self.style.map("Treeview.Heading", background=[("active", colors["panel"])])
        self.style.configure(
            "Horizontal.TScale", background=colors["background"],
            troughcolor=colors["trough"],
        )
        self._configure_volume_slider_style(colors["trough"])
        self._configure_scrollbar_styles(colors["trough"], colors["border"])

    def _configure_scrollbar_styles(self, trough_color: str, border_color: str) -> None:
        """Use the selected slider color for both process-list scrollbars."""
        if self.style is None:
            return
        for orientation in ("Vertical", "Horizontal"):
            style_name = f"App.{orientation}.TScrollbar"
            self.style.configure(
                style_name,
                background=self.slider_thumb_color,
                troughcolor=trough_color,
                bordercolor=border_color,
                lightcolor=self.slider_thumb_color,
                darkcolor=self.slider_thumb_color,
                arrowcolor=self.slider_thumb_color,
                relief="flat",
            )
            self.style.map(
                style_name,
                background=[
                    ("active", self.slider_thumb_color),
                    ("pressed", self.slider_thumb_color),
                    ("disabled", self.slider_thumb_color),
                ],
            )

    def _configure_volume_slider_style(self, trough_color: str | None = None) -> None:
        """Use the same customizable, high-contrast slider in both themes."""
        if self.style is None:
            return
        if trough_color is None:
            trough_color = "#d9e0e9" if self.theme == "light" else "#3b4555"
        self.style.configure(
            "Volume.Horizontal.TScale",
            background=self.slider_thumb_color,
            troughcolor=trough_color,
            bordercolor=self.slider_thumb_color,
            lightcolor=self.slider_thumb_color,
            darkcolor=self.slider_thumb_color,
            focuscolor=self.slider_thumb_color,
            borderwidth=0,
            sliderlength=22,
            sliderthickness=16,
            # A flat thumb avoids the light/dark bevel spots drawn by the
            # classic raised style, making the slider look like a single solid fill.
            sliderrelief="flat",
        )
        self.style.map(
            "Volume.Horizontal.TScale",
            background=[("active", self.slider_thumb_color), ("disabled", self.slider_thumb_color)],
            relief=[("pressed", "flat"), ("active", "flat")],
        )

    def _set_slider_thumb_color(self, color: str) -> None:
        """Update the visible slider; persistence is handled separately."""
        self.slider_thumb_color = normalize_hex_color(color)
        self._configure_volume_slider_style()
        colors = {
            "light": ("#d9e0e9", "#d4dce7"),
            "dark": ("#3b4555", "#3b4555"),
        }[self.theme]
        self._configure_scrollbar_styles(*colors)

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
        # The GUI layout test builds the UI with an object created via __new__.
        # Make that focused test path use the same default style as a fresh install.
        if getattr(self, "style", None) is None:
            self._apply_theme(getattr(self, "theme", "light"))
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
        ttk.Button(heading_actions, text="Refresh list", command=self._scan_sessions).pack(side="left")

        ttk.Label(
            outer,
            text=(
                "Lists running processes with audio. Audio sessions counts the separate Windows "
                "sessions owned by each process; a rule adjusts each session. Saved rules apply "
                "when matching sessions appear."
            ),
            wraplength=1080,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(4, 6))

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

        # The Treeview must be created with its actual layout container as its
        # Tk parent. Using outer as parent and packing it into table_frame via
        # pack(in_=...) made the widget get covered by the frame on Windows, so
        # sessions were detected but the table appeared blank.
        self.table_frame = ttk.Frame(outer)
        self.table_frame.grid(row=3, column=0, sticky="nsew")

        columns = ("checked", "application", "pid", "sessions", "details", "current", "target", "status")
        self.table = ttk.Treeview(
            self.table_frame, columns=columns, show="headings", height=7, selectmode="browse"
        )
        for column, title in (
            ("checked", "Select"),
            ("application", "Process"),
            ("pid", "PID"),
            ("sessions", "Sessions"),
            ("details", "Session / device"),
            ("current", "Current"),
            ("target", "Target"),
            ("status", "Rule status"),
        ):
            self.table.heading(column, text=title)
        self.table.column("checked", width=60, minwidth=60, anchor="center", stretch=False)
        self.table.column("application", width=140, minwidth=110, stretch=False)
        self.table.column("pid", width=60, minwidth=60, anchor="center", stretch=False)
        self.table.column("sessions", width=80, minwidth=80, anchor="center", stretch=False)
        self.table.column("details", width=170, minwidth=130, stretch=False)
        self.table.column("current", width=84, minwidth=84, anchor="center", stretch=False)
        self.table.column("target", width=84, minwidth=84, anchor="center", stretch=False)
        self.table.column("status", width=150, minwidth=120, stretch=False)
        self.table.bind("<Button-1>", self._on_table_click)
        self.table.bind("<Configure>", self._on_table_resize, add="+")

        self.vertical_scrollbar = ttk.Scrollbar(
            self.table_frame, orient="vertical", command=self.table.yview,
            style="App.Vertical.TScrollbar",
        )
        self.horizontal_scrollbar = ttk.Scrollbar(
            self.table_frame, orient="horizontal", command=self.table.xview,
            style="App.Horizontal.TScrollbar",
        )
        self.table.configure(
            yscrollcommand=self._set_vertical_scrollbar,
            xscrollcommand=self.horizontal_scrollbar.set,
        )
        self.table.grid(row=0, column=0, sticky="nsew")
        self.vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        self.horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)

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
        ttk.Checkbutton(
            startup_controls,
            text="Start with Windows",
            variable=self.startup_var,
            command=self.change_startup,
        ).grid(row=0, column=0, sticky="w")
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
        self.root.after_idle(self._on_table_resize)

    def _set_vertical_scrollbar(self, first: str, last: str) -> None:
        """Show the colored process scrollbar only when the table can scroll."""
        scrollbar = getattr(self, "vertical_scrollbar", None)
        if scrollbar is None:
            return
        scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            scrollbar.grid_remove()
        else:
            scrollbar.grid(row=0, column=1, sticky="ns")

    def _on_table_resize(self, event=None) -> None:
        """Fit the process columns to the current width, scrolling only if needed."""
        if event is not None and event.widget is not self.table:
            return
        if not hasattr(self, "table") or not self.table.winfo_exists():
            return
        available = self.table.winfo_width() - 4
        if available < 100:
            return  # Geometry is not settled yet; the next Configure event retries.

        fixed_widths = {
            "checked": 60,
            "pid": 60,
            "sessions": 80,
            "current": 84,
            "target": 84,
        }
        flexible_minimums = {"application": 110, "details": 130, "status": 120}
        minimum_total = sum(fixed_widths.values()) + sum(flexible_minimums.values())
        if available >= minimum_total:
            remaining = available - minimum_total
            weights = {"application": 1.0, "details": 1.5, "status": 1.1}
            total_weight = sum(weights.values())
            widths = dict(fixed_widths)
            allocated = 0
            for column in ("application", "details"):
                extra = int(remaining * weights[column] / total_weight)
                widths[column] = flexible_minimums[column] + extra
                allocated += extra
            widths["status"] = (
                flexible_minimums["status"] + remaining - allocated
            )
            for column, width in widths.items():
                self.table.column(column, width=width, stretch=False)
            self.horizontal_scrollbar.grid_remove()
        else:
            # Preserve readable minimums on unusually narrow displays and let
            # the user reach the remaining columns with the horizontal scrollbar.
            for column, width in {**fixed_widths, **flexible_minimums}.items():
                self.table.column(column, width=width, stretch=False)
            self.horizontal_scrollbar.grid(row=1, column=0, sticky="ew")

    def _on_root_resize(self, event) -> None:
        """Adapt the status line to the available footer width during resizing."""
        if event.widget is not self.root or not hasattr(self, "status_label"):
            return
        try:
            available = max(180, self.root.winfo_width() - 390)
            self.status_label.configure(wraplength=min(560, available))
        except tk.TclError:
            pass

    def _start_tray_icon(self) -> None:
        try:
            import pystray
            from PIL import Image

            with Image.open(resource_path("assets/app-icon.png")) as source:
                image = source.convert("RGBA")
                image.thumbnail((64, 64), Image.Resampling.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem("Open", self._tray_show, default=True),
                pystray.MenuItem("Reapply saved volumes", self._tray_reapply),
                pystray.MenuItem("Exit", self._tray_exit),
            )
            self.tray_icon = pystray.Icon("AppVolumeManager", image, APP_NAME, menu)
            self.tray_icon.run_detached()
        except Exception as exc:
            # The main window still works if the tray library can't initialize.
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
        self._schedule_poll(2000)
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def hide_to_tray(self) -> None:
        if self.tray_icon is None:
            self.root.iconify()
            self.window_visible = False
            self._schedule_poll(
                refresh_interval_ms(
                    False, bool(
                        self.audio_monitor and self.audio_monitor.is_ready
                        and not self.audio_monitor.last_error
                    )
                )
            )
            self.status_var.set("System tray unavailable; window minimized instead.")
            return
        self.root.withdraw()
        self.window_visible = False
        self._schedule_poll(
            refresh_interval_ms(
                False, bool(
                    self.audio_monitor and self.audio_monitor.is_ready
                    and not self.audio_monitor.last_error
                )
            )
        )

    def _on_visibility_event(self, _event=None) -> None:
        if not self._closing:
            try:
                self.root.after_idle(self._sync_window_visibility)
            except tk.TclError:
                pass

    def _sync_window_visibility(self) -> None:
        if self._closing:
            return
        try:
            visible = self.root.state() == "normal"
        except tk.TclError:
            return
        if visible == self.window_visible:
            return
        self.window_visible = visible
        if visible:
            # On restore, refresh immediately rather than waiting for the next timer.
            self._scan_sessions(update_table=True)
            self._schedule_poll(2000)
        else:
            ready = bool(
                self.audio_monitor
                and self.audio_monitor.is_ready
                and not self.audio_monitor.last_error
            )
            self._schedule_poll(refresh_interval_ms(False, ready))

    def _queue_audio_event(self) -> None:
        if not self._closing:
            self._audio_event_queue.put(True)

    def _apply_notified_session(self, session) -> None:
        """Apply a persistent rule on the Core Audio callback thread immediately."""
        if self._closing:
            return
        self.engine.apply_new_session(session, tuple(self.rules))
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
        # _refresh_table rebuilds the rows to update their checkbox symbols.
        # Restore the blue Treeview highlight for the row the user clicked.
        if row_id in self.table.get_children():
            self.table.selection_set(row_id)
            self.table.focus(row_id)
        return "break"

    def _clear_process_search(self, _event=None) -> str:
        """Clear the process filter and return focus to the search field."""
        search_var = getattr(self, "search_var", None)
        if search_var is not None:
            search_var.set("")
        search_entry = getattr(self, "search_entry", None)
        if search_entry is not None:
            try:
                search_entry.focus_set()
            except tk.TclError:
                pass
        return "break"

    @staticmethod
    def _row_matches_search(row: ProcessRow, query: str) -> bool:
        """Case-insensitively match each search term against process details."""
        terms = query.casefold().split()
        if not terms:
            return True

        searchable_fields = [
            row.executable,
            row.process_role,
            "active" if row.active else "waiting",
            str(row.process_id) if row.process_id is not None else "",
            str(row.session_count),
            *(str(volume) for volume in row.current_volumes),
            *row.session_details,
        ]
        if row.rule is not None:
            searchable_fields.extend((
                str(row.rule.volume),
                "enabled" if row.rule.enabled else "disabled",
                "process profile" if row.rule.is_process_specific else "app rule",
            ))
        searchable_text = " ".join(searchable_fields).casefold()
        return all(term in searchable_text for term in terms)

    def _update_target_label(self, value: str) -> None:
        volume = max(0, min(100, int(float(value) + 0.5)))
        self.target_volume_label.set(f"Volume for selected: {volume}%")

    def edit_slider_thumb_color(self) -> None:
        """Open the separate slider color editor."""
        show_slider_color_dialog(
            self.root,
            self.slider_thumb_color,
            self.preference_store,
            self._set_slider_thumb_color,
            self.status_var,
        )

    def _selected_rows(self) -> list[ProcessRow]:
        rows = getattr(self, "_all_row_info", self._row_info)
        return [rows[row_id] for row_id in self.checked_rows if row_id in rows]

    def apply_to_selected(self) -> None:
        selected = self._selected_rows()
        if not selected:
            messagebox.showinfo(APP_NAME, "Tick one or more rows in the Select column first.")
            return

        target = max(0, min(100, int(self.target_volume_var.get() + 0.5)))
        updated = {rule.key: rule for rule in self.rules}
        persistent_count = 0
        temporary_rows: list[ProcessRow] = []
        active_rows = [row for row in selected if row.active and row.process_id is not None]
        saved_rows = [row for row in selected if not row.active and row.rule is not None]

        # Editing a saved row preserves whether its rule targets the whole app
        # or a repeatable process profile.
        for row in saved_rows:
            old_rule = row.rule
            updated[old_rule.key] = AppRule(
                old_rule.executable,
                target,
                old_rule.enabled,
                process_signature=old_rule.process_signature,
                process_role=old_rule.process_role,
            )
            persistent_count += 1

        all_rows = getattr(self, "_all_row_info", self._row_info)
        live_rows = [
            row for row in all_rows.values()
            if row.active and row.process_id is not None
        ]
        active_signature_counts: dict[str, int] = {}
        for row in live_rows:
            if row.process_signature:
                signature = row.process_signature
                active_signature_counts[signature] = active_signature_counts.get(signature, 0) + 1

        selected_signature_counts: dict[str, int] = {}
        for row in active_rows:
            if row.process_signature:
                signature = row.process_signature
                selected_signature_counts[signature] = selected_signature_counts.get(signature, 0) + 1

        handled_signatures: set[str] = set()
        for row in active_rows:
            signature = row.process_signature
            if not signature:
                temporary_rows.append(row)
                continue
            if signature in handled_signatures:
                continue
            handled_signatures.add(signature)

            matching_count = active_signature_counts.get(signature, 0)
            selected_count = selected_signature_counts.get(signature, 0)
            save_for_role = selected_count >= matching_count
            if selected_count < matching_count:
                save_for_role = messagebox.askyesno(
                    APP_NAME,
                    f"{row.executable} has {matching_count} running processes with the same profile. "
                    "Saving this rule will affect all of them, including unchecked processes, "
                    "and matching processes started later.\n\n"
                    "Yes: save for this profile.\n"
                    "No: apply only to checked processes until they exit.",
                )

            if save_for_role:
                updated[f"process:{row.executable.casefold()}:{signature}"] = AppRule(
                    row.executable,
                    target,
                    True,
                    process_signature=signature,
                    process_role=row.process_role,
                )
                persistent_count += 1
            else:
                temporary_rows.extend(
                    candidate for candidate in active_rows if candidate.process_signature == signature
                )

        # De-duplicate temporary rows, since a selected set can include multiple
        # representations of the same process only when data from devices overlaps.
        temporary_unique = {
            (row.process_id, row.executable.casefold()): row for row in temporary_rows
        }
        new_rules = sorted(updated.values(), key=lambda rule: (rule.executable.casefold(), rule.key))

        if persistent_count:
            try:
                self.store.save_rules(new_rules)
            except SettingsError as exc:
                messagebox.showerror(APP_NAME, str(exc))
                return
            self.rules = new_rules

        persistent_signatures = {
            rule.process_signature for rule in updated.values()
            if rule.is_process_specific and rule.process_signature is not None
        }
        if persistent_signatures:
            self.temporary_process_targets = {
                key: value for key, value in self.temporary_process_targets.items()
                if not any(
                    row.process_id == key[0]
                    and row.executable.casefold() == key[1]
                    and row.process_signature in persistent_signatures
                    for row in all_rows.values()
                )
            }
        for process_key in temporary_unique:
            self.temporary_process_targets[process_key] = target

        if persistent_count or temporary_unique:
            self.engine.reset()
            self._scan_sessions(force=True)
        if persistent_count and temporary_unique:
            self.status_var.set(
                f"Saved {persistent_count} rule(s); applied temporarily to "
                f"{len(temporary_unique)} selected process instance(s) that can't be matched safely after restart."
            )
        elif persistent_count:
            self.status_var.set(
                f"Saved {persistent_count} rule(s). Process profiles match the same executable profile "
                "after restart; app rules affect every matching process."
            )
        elif temporary_unique:
            self.status_var.set(
                f"Applied {target}% to {len(temporary_unique)} checked process instance(s) for this run only. "
                "Use Add rule for app for a persistent rule when a process profile can't be identified."
            )
        self._refresh_table()

    def remove_selected(self) -> None:
        selected = self._selected_rows()
        if not selected:
            messagebox.showinfo(APP_NAME, "Tick one or more rows in the Select column first.")
            return

        rules_to_remove = {row.rule.key: row.rule for row in selected if row.rule is not None}
        if not rules_to_remove:
            messagebox.showinfo(APP_NAME, "The selected process(es) have no saved volume rule to remove.")
            return

        descriptions = []
        for rule in rules_to_remove.values():
            if rule.is_process_specific:
                descriptions.append(f"{rule.executable} — matching process profile only")
            else:
                descriptions.append(f"{rule.executable} — all processes using this app")
        if not messagebox.askyesno(
            APP_NAME,
            "Remove these saved volume rule(s)?\n\n" + "\n".join(sorted(descriptions, key=str.casefold)),
        ):
            return

        remove_keys = set(rules_to_remove)
        new_rules = [rule for rule in self.rules if rule.key not in remove_keys]
        try:
            self.store.save_rules(new_rules)
        except SettingsError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return

        self.rules = new_rules
        self.engine.reset()
        self._refresh_table()
        self.status_var.set(f"Removed {len(remove_keys)} saved rule(s). Current volumes are not reset.")

    def add_rule(self) -> None:
        self._rule_dialog(None)

    def _rule_dialog(self, existing: AppRule | None) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Add application rule" if existing is None else "Edit application rule")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Executable name. This rule applies to every process using this executable.").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        name_var = tk.StringVar(value=existing.executable if existing else "")
        name_entry = ttk.Entry(frame, textvariable=name_var, width=38)
        name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        ttk.Button(
            frame, text="Browse…", command=lambda: self._browse_executable(name_var)
        ).grid(row=1, column=1, padx=(6, 0), pady=(4, 4))

        available_names = sorted({session.executable for session in self.last_sessions}, key=str.casefold)
        ttk.Label(frame, text="Or choose a detected executable").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        detected_var = tk.StringVar(value="")
        detected = ttk.Combobox(frame, textvariable=detected_var, values=available_names, width=35, state="readonly")
        detected.grid(row=3, column=0, sticky="ew", pady=(4, 4))
        detected.bind("<<ComboboxSelected>>", lambda _event: name_var.set(detected_var.get()))

        volume_var = tk.DoubleVar(value=existing.volume if existing else int(self.target_volume_var.get()))
        volume_label_var = tk.StringVar(value=f"Target volume: {int(volume_var.get())}%")
        ttk.Label(frame, textvariable=volume_label_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        scale = ttk.Scale(
            frame,
            from_=0,
            to=100,
            orient="horizontal",
            length=330,
            variable=volume_var,
            command=lambda value: self._update_volume_label(volume_var, volume_label_var, value),
            takefocus=True,
            style="Volume.Horizontal.TScale",
        )
        scale.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        scale.bind("<Button-1>", allow_scale_thumb_click)
        enabled_var = tk.BooleanVar(value=existing.enabled if existing else True)
        ttk.Checkbutton(frame, text="Apply this rule automatically", variable=enabled_var).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(2, 8)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))

        def save() -> None:
            try:
                new_rule = AppRule(name_var.get(), int(round(volume_var.get())), enabled_var.get())
                new_rules = [rule for rule in self.rules if rule.key != new_rule.key]
                new_rules.append(new_rule)
                new_rules.sort(key=lambda rule: rule.executable.casefold())
                self.store.save_rules(new_rules)
                self.rules = new_rules
                self.engine.reset()
                self._scan_sessions(force=True)
                self.status_var.set(
                    f"Saved {new_rule.executable}; waiting for its audio session if it isn't active."
                )
                dialog.destroy()
            except (ValueError, SettingsError) as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=dialog)

        ttk.Button(buttons, text="Save rule", command=save).pack(side="right")
        name_entry.focus_set()
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        self.root.wait_window(dialog)

    @staticmethod
    def _update_volume_label(variable: tk.DoubleVar, label: tk.StringVar, value: str) -> None:
        volume = max(0, min(100, int(float(value) + 0.5)))
        variable.set(volume)
        label.set(f"Target volume: {volume}%")

    @staticmethod
    def _browse_executable(name_var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            title="Choose application executable",
            filetypes=[("Windows applications", "*.exe"), ("All files", "*.*")],
        )
        if path:
            name_var.set(Path(path).name)

    def _update_startup_status(self) -> None:
        self.startup_status_var.set(
            "Starts when you sign in" if self.startup_var.get() else "Not enabled"
        )

    def change_startup(self) -> None:
        requested = bool(self.startup_var.get())
        try:
            set_startup_enabled(requested)
            self._update_startup_status()
        except OSError as exc:
            self.startup_var.set(not requested)
            self._update_startup_status()
            messagebox.showerror(APP_NAME, f"Could not update Windows startup setting:\n{exc}")

    def open_settings_folder(self) -> None:
        path = self.store.path.parent
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows-only app
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Could not open settings folder:\n{exc}")

    def reapply_now(self) -> None:
        self.engine.reset()
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

    def _poll_sessions(self) -> None:
        self._poll_after_id = None
        if self._closing:
            return
        monitor_ready = bool(
            self.audio_monitor
            and self.audio_monitor.is_ready
            and not self.audio_monitor.last_error
        )
        # In the tray, new sessions are handled by Core Audio events. A 60-second
        # safety sweep catches missed notifications; if events cannot be registered,
        # fall back to 5-second polling so automation still works.
        self._scan_sessions(update_table=self.window_visible)
        if not self._closing:
            self._schedule_poll(refresh_interval_ms(self.window_visible, monitor_ready))

    def _process_audio_events(self) -> None:
        self._audio_event_after_id = None
        if self._closing:
            return
        has_changes = False
        while True:
            try:
                self._audio_event_queue.get_nowait()
                has_changes = True
            except queue.Empty:
                break
        if has_changes:
            self._scan_sessions(update_table=self.window_visible)
        if not self._closing:
            self._audio_event_after_id = self.root.after(
                AUDIO_EVENT_CHECK_MS, self._process_audio_events
            )

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
            live_processes = {
                (session.process_id, session.executable.casefold())
                for session in self.last_sessions
                if session.process_id is not None
            }
            self.temporary_process_targets = {
                key: target for key, target in self.temporary_process_targets.items()
                if key in live_processes
            }
            result = self.engine.scan(
                self.last_sessions,
                self.rules,
                force=force,
                temporary_targets=self.temporary_process_targets,
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
            warnings = getattr(self.backend, "last_warnings", [])
            if warnings and not result.errors:
                self.status_var.set(
                    f"Found {process_count} process(es) with audio; {len(warnings)} device warning(s). "
                    "Some non-default outputs may be missing."
                )
        except Exception as exc:
            self.status_var.set(f"Audio scan failed; will retry: {exc}")
        if update_table:
            self._refresh_table()

    def _refresh_table(self) -> None:
        previous_selection = self.table.selection()
        highlighted_row = previous_selection[0] if previous_selection else None
        all_rows = build_process_rows(self.last_sessions, self.rules)
        self._all_row_info = {row.row_id: row for row in all_rows}
        # Filtering changes only which rows are drawn. Checked processes stay
        # checked while hidden by a query, and can still be acted on safely.
        self.checked_rows.intersection_update(self._all_row_info)
        query = getattr(self, "search_var", None)
        search_text = query.get().strip() if query is not None else ""
        rows = [row for row in all_rows if self._row_matches_search(row, search_text)]
        self._row_info = {row.row_id: row for row in rows}
        summary_var = getattr(self, "search_summary_var", None)
        if summary_var is not None:
            summary_var.set(
                f"{len(rows)} shown  ·  {len(self.checked_rows)} selected"
            )

        for item in self.table.get_children():
            self.table.delete(item)
        if not rows:
            if all_rows:
                placeholder_id = "no-search-matches"
                values = (
                    "—", "No matching processes", "—", "—", "—", "—", "—",
                    "Clear the search to see all processes",
                )
            else:
                placeholder_id = "no-audio-sessions"
                values = (
                    "—", "No audio sessions", "—", "0", "—", "—", "—",
                    "Play sound in an app, then refresh",
                )
            self.table.insert(
                "", "end", iid=placeholder_id, values=values,
            )
            self._sync_volume_scale_enabled()
            return

        for row in rows:
            if row.current_volumes:
                current_volume = (
                    f"{row.current_volumes[0]}%"
                    if len(row.current_volumes) == 1
                    else "Mixed"
                )
            else:
                current_volume = "—"
            temporary_target = None
            if row.active and row.process_id is not None:
                temporary_target = self.temporary_process_targets.get(
                    (row.process_id, row.executable.casefold())
                )
            target = (
                f"{temporary_target}%" if temporary_target is not None
                else f"{row.rule.volume}%" if row.rule is not None
                else "—"
            )
            if not row.active:
                if row.rule and not row.rule.enabled:
                    status = "Saved rule disabled"
                elif row.rule and row.rule.is_process_specific:
                    status = "Waiting for matching profile"
                else:
                    status = "Waiting for app audio"
                process_id = "—"
                session_count = "0"
            else:
                process_id = str(row.process_id) if row.process_id is not None else "Unknown"
                session_count = str(row.session_count)
                if temporary_target is not None:
                    status = "Temporary process target"
                elif row.rule is None:
                    status = "Not configured"
                elif not row.rule.enabled:
                    status = "Rule disabled"
                elif row.rule.is_process_specific:
                    status = "Saved process profile"
                else:
                    status = "App rule"
            checked = "☑" if row.row_id in self.checked_rows else "☐"
            details = "; ".join(row.session_details) or "—"
            self.table.insert(
                "", "end", iid=row.row_id,
                values=(checked, row.executable, process_id, session_count, details,
                        current_volume, target, status),
            )
        # The table is rebuilt during automatic refreshes. Restore the blue
        # row highlight while the underlying process is still present.
        if highlighted_row in self._row_info:
            self.table.selection_set(highlighted_row)
            self.table.focus(highlighted_row)
        self._sync_volume_scale_enabled()

    def _sync_volume_scale_enabled(self) -> None:
        """Only allow volume adjustments when at least one process is checked."""
        scale = getattr(self, "volume_scale", None)
        if scale is None:
            return
        has_selection = bool(self._selected_rows())
        try:
            scale.state(["!disabled"] if has_selection else ["disabled"])
        except tk.TclError:
            pass
        label = getattr(self, "target_volume_label", None)
        volume_var = getattr(self, "target_volume_var", None)
        if label is not None and volume_var is not None:
            if has_selection:
                volume = int(float(volume_var.get()) + 0.5)
                label.set(f"Volume for selected: {volume}%")
            else:
                label.set("Select a process to change volume")

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for callback_id in (self._poll_after_id, self._audio_event_after_id):
            if callback_id is not None:
                try:
                    self.root.after_cancel(callback_id)
                except tk.TclError:
                    pass
        if self.audio_monitor is not None:
            self.audio_monitor.stop()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.backend.shutdown()
        self.root.destroy()
        if self._native_icon_handle and sys.platform == "win32":
            try:
                destroy_icon = ctypes.windll.user32.DestroyIcon
                destroy_icon.argtypes = [ctypes.c_void_p]
                destroy_icon.restype = ctypes.c_int
                destroy_icon(ctypes.c_void_p(self._native_icon_handle))
            except (AttributeError, OSError):
                pass
            self._native_icon_handle = None


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--minimized", action="store_true", help="Start hidden in the system tray")
    args = parser.parse_args()
    if sys.platform != "win32":
        print("App Volume Manager is a Windows-only application.", file=sys.stderr)
        return 1
    set_windows_app_identity()
    root = tk.Tk()
    VolumeManagerApp(root, start_minimized=args.minimized)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
