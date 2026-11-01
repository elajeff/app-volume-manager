"""Modal dialog for saving a volume rule for an executable."""

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_volume_manager.rules import AppRule
from app_volume_manager.settings import SettingsError
from app_volume_manager.ui import APP_NAME
from app_volume_manager.ui.volume_scale import allow_scale_thumb_click, percent


def show_rule_dialog(
    parent: tk.Misc,
    detected_names: list[str],
    initial_volume: int,
    save_rule: Callable[[AppRule], None],
) -> None:
    """Ask for an executable and volume, then hand the rule to `save_rule`.

    The dialog closes once `save_rule` returns. If it raises ValueError or
    SettingsError, the message is shown and the dialog stays open.
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Add application rule")
    dialog.transient(parent)
    dialog.resizable(False, False)
    frame = ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Executable name. This rule applies to every process using this executable.").grid(
        row=0, column=0, columnspan=2, sticky="w"
    )
    name_var = tk.StringVar(value="")
    name_entry = ttk.Entry(frame, textvariable=name_var, width=38)
    name_entry.grid(row=1, column=0, sticky="ew", pady=(4, 4))
    ttk.Button(
        frame, text="Browse…", command=lambda: _browse_executable(name_var)
    ).grid(row=1, column=1, padx=(6, 0), pady=(4, 4))

    ttk.Label(frame, text="Or choose a detected executable").grid(
        row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
    )
    detected_var = tk.StringVar(value="")
    detected = ttk.Combobox(frame, textvariable=detected_var, values=detected_names, width=35, state="readonly")
    detected.grid(row=3, column=0, sticky="ew", pady=(4, 4))
    detected.bind("<<ComboboxSelected>>", lambda _event: name_var.set(detected_var.get()))

    volume_var = tk.DoubleVar(value=initial_volume)
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
        command=lambda value: _update_volume_label(volume_var, volume_label_var, value),
        takefocus=True,
        style="Volume.Horizontal.TScale",
    )
    scale.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 8))
    scale.bind("<Button-1>", allow_scale_thumb_click)
    enabled_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text="Apply this rule automatically", variable=enabled_var).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=(2, 8)
    )

    buttons = ttk.Frame(frame)
    buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))

    def save() -> None:
        try:
            save_rule(AppRule(name_var.get(), percent(volume_var.get()), enabled_var.get()))
            dialog.destroy()
        except (ValueError, SettingsError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=dialog)

    ttk.Button(buttons, text="Save rule", command=save).pack(side="right")
    name_entry.focus_set()
    dialog.bind("<Return>", lambda _event: save())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    dialog.grab_set()
    parent.wait_window(dialog)


def _update_volume_label(variable: tk.DoubleVar, label: tk.StringVar, value: str) -> None:
    volume = percent(value)
    variable.set(volume)
    label.set(f"Target volume: {volume}%")


def _browse_executable(name_var: tk.StringVar) -> None:
    path = filedialog.askopenfilename(
        title="Choose application executable",
        filetypes=[("Windows applications", "*.exe"), ("All files", "*.*")],
    )
    if path:
        name_var.set(Path(path).name)
