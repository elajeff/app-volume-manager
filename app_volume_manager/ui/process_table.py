"""The process table with its scrollbars and column fitting."""

import tkinter as tk
from collections.abc import Callable, Collection
from tkinter import ttk

HEADINGS = (
    ("checked", "Select"),
    ("application", "Process"),
    ("pid", "PID"),
    ("sessions", "Sessions"),
    ("details", "Session / device"),
    ("current", "Current"),
    ("target", "Target"),
    ("status", "Rule status"),
)


class ProcessTable:
    def __init__(self, parent: tk.Misc, on_click: Callable) -> None:
        # Parent the Treeview to the frame itself; parenting it to the window
        # and packing it in with in_= left it covered on Windows (a blank table).
        self.frame = ttk.Frame(parent)
        self.tree = ttk.Treeview(
            self.frame, columns=[name for name, _title in HEADINGS],
            show="headings", height=7, selectmode="browse",
        )
        for column, title in HEADINGS:
            self.tree.heading(column, text=title)
        self.tree.column("checked", width=60, minwidth=60, anchor="center", stretch=False)
        self.tree.column("application", width=140, minwidth=110, stretch=False)
        self.tree.column("pid", width=60, minwidth=60, anchor="center", stretch=False)
        self.tree.column("sessions", width=80, minwidth=80, anchor="center", stretch=False)
        self.tree.column("details", width=170, minwidth=130, stretch=False)
        self.tree.column("current", width=84, minwidth=84, anchor="center", stretch=False)
        self.tree.column("target", width=84, minwidth=84, anchor="center", stretch=False)
        self.tree.column("status", width=150, minwidth=120, stretch=False)
        self.tree.bind("<Button-1>", on_click)
        self.tree.bind("<Configure>", self.fit_columns, add="+")

        self.vertical_scrollbar = ttk.Scrollbar(
            self.frame, orient="vertical", command=self.tree.yview,
            style="App.Vertical.TScrollbar",
        )
        self.horizontal_scrollbar = ttk.Scrollbar(
            self.frame, orient="horizontal", command=self.tree.xview,
            style="App.Horizontal.TScrollbar",
        )
        self.tree.configure(
            yscrollcommand=self._set_vertical_scrollbar,
            xscrollcommand=self.horizontal_scrollbar.set,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        self.horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        self._shown: dict[str, tuple] = {}

    def show(self, rows: dict[str, tuple], selectable: Collection[str]) -> None:
        """Display `rows` (row id -> cell values), touching as little as possible.

        When the same rows come back in the same order only the changed cells
        are updated. Otherwise the table is rebuilt and the highlighted row is
        kept if it is still shown and listed in `selectable`.
        """
        if list(rows) == list(self._shown):
            for row_id, values in rows.items():
                if values != self._shown[row_id]:
                    self.tree.item(row_id, values=values)
        else:
            previous_selection = self.tree.selection()
            self.tree.delete(*self.tree.get_children())
            for row_id, values in rows.items():
                self.tree.insert("", "end", iid=row_id, values=values)
            if previous_selection and previous_selection[0] in selectable:
                self.tree.selection_set(previous_selection[0])
                self.tree.focus(previous_selection[0])
        self._shown = rows

    def _set_vertical_scrollbar(self, first: str, last: str) -> None:
        """Show the colored process scrollbar only when the table can scroll."""
        self.vertical_scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.vertical_scrollbar.grid_remove()
        else:
            self.vertical_scrollbar.grid(row=0, column=1, sticky="ns")

    def fit_columns(self, event=None) -> None:
        """Fit the process columns to the current width, scrolling only if needed."""
        if event is not None and event.widget is not self.tree:
            return
        available = self.tree.winfo_width() - 4
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
                self.tree.column(column, width=width, stretch=False)
            self.horizontal_scrollbar.grid_remove()
        else:
            # Preserve readable minimums on unusually narrow displays and let
            # the user reach the remaining columns with the horizontal scrollbar.
            for column, width in {**fixed_widths, **flexible_minimums}.items():
                self.tree.column(column, width=width, stretch=False)
            self.horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
