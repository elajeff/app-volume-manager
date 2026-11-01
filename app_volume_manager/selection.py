"""Decide what applying or removing a volume for the checked rows should change."""

import threading
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import psutil

from app_volume_manager.process_list import ProcessRow
from app_volume_manager.rules import AppRule

# A temporary target is keyed by (process id, lowercase executable name).
TargetKey = tuple[int, str]


def target_key(row: ProcessRow) -> TargetKey:
    return row.process_id, row.executable.casefold()


class TemporaryTargets:
    """Volume targets that last only while the targeted process instance runs.

    The Core Audio callback thread reads these while the UI thread changes them,
    so every access takes the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._targets: dict[TargetKey, int] = {}
        self._processes: dict[TargetKey, psutil.Process] = {}

    def add(self, key: TargetKey, target: int, process: psutil.Process) -> None:
        with self._lock:
            self._targets[key] = target
            self._processes[key] = process

    def get(self, key: TargetKey) -> int | None:
        with self._lock:
            return self._targets.get(key)

    def __contains__(self, key: TargetKey) -> bool:
        with self._lock:
            return key in self._targets

    def discard(self, keys: Iterable[TargetKey]) -> None:
        with self._lock:
            for key in keys:
                self._targets.pop(key, None)
                self._processes.pop(key, None)

    def _check(self) -> tuple[dict[TargetKey, int], list[tuple[TargetKey, psutil.Process | None]]]:
        with self._lock:
            entries = [(key, target, self._processes.get(key)) for key, target in self._targets.items()]
        live: dict[TargetKey, int] = {}
        dead = []
        for key, target, process in entries:
            if process is not None and process.is_running():
                live[key] = target
            else:
                dead.append((key, process))
        return live, dead

    def live(self) -> dict[TargetKey, int]:
        """Return the targets whose process is still the one that was selected."""
        return self._check()[0]

    def prune(self) -> dict[TargetKey, int]:
        """Forget targets whose process has exited, and return the remaining ones."""
        live, dead = self._check()
        with self._lock:
            for key, process in dead:
                # Skip a key that was re-added for a different process meanwhile.
                if self._processes.get(key) is process:
                    self._targets.pop(key, None)
                    self._processes.pop(key, None)
        return live


def identify_processes(keys: Iterable[TargetKey]) -> dict[TargetKey, psutil.Process]:
    """Look up each process, raising psutil.Error if one has already exited."""
    processes = {}
    for key in keys:
        process = psutil.Process(key[0])
        if not process.is_running():
            raise psutil.NoSuchProcess(key[0])
        processes[key] = process
    return processes


@dataclass(frozen=True)
class ApplyPlan:
    rules: list[AppRule]
    persistent_count: int
    temporary_keys: tuple[TargetKey, ...]
    superseded_keys: frozenset[TargetKey]


def plan_apply(
    selected: list[ProcessRow],
    all_rows: Mapping[str, ProcessRow],
    rules: Iterable[AppRule],
    target: int,
    confirm_profile: Callable[[ProcessRow, int], bool],
) -> ApplyPlan:
    """Work out the rules to save and the processes to target for this run only.

    `confirm_profile(row, matching_count)` is asked when a profile rule would
    also reach running processes that were not checked.
    """
    updated = {rule.key: rule for rule in rules}
    persistent_count = 0
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

    running_counts = Counter(
        row.process_signature for row in all_rows.values()
        if row.active and row.process_id is not None and row.process_signature
    )
    selected_counts = Counter(row.process_signature for row in active_rows if row.process_signature)

    temporary_rows: list[ProcessRow] = []
    handled_signatures: set[str] = set()
    for row in active_rows:
        signature = row.process_signature
        if not signature:
            temporary_rows.append(row)
            continue
        if signature in handled_signatures:
            continue
        handled_signatures.add(signature)

        matching_count = running_counts[signature]
        save_for_role = selected_counts[signature] >= matching_count or confirm_profile(row, matching_count)
        if save_for_role:
            profile_rule = AppRule(
                row.executable,
                target,
                True,
                process_signature=signature,
                process_role=row.process_role,
            )
            updated[profile_rule.key] = profile_rule
            persistent_count += 1
        else:
            temporary_rows.extend(candidate for candidate in active_rows if candidate.process_signature == signature)

    # A selected set can hold the same process twice when devices overlap.
    temporary_keys = tuple(dict.fromkeys(target_key(row) for row in temporary_rows))

    persistent_signatures = {
        rule.process_signature for rule in updated.values() if rule.is_process_specific
    }
    superseded = frozenset(
        target_key(row) for row in all_rows.values()
        if row.process_id is not None and row.process_signature in persistent_signatures
    )
    new_rules = sorted(updated.values(), key=lambda rule: (rule.executable.casefold(), rule.key))
    return ApplyPlan(new_rules, persistent_count, temporary_keys, superseded)


@dataclass(frozen=True)
class RemovalPlan:
    rules: tuple[AppRule, ...]
    temporary_keys: frozenset[TargetKey]

    @property
    def is_empty(self) -> bool:
        return not self.rules and not self.temporary_keys

    def descriptions(self) -> list[str]:
        lines = [f"{executable} (PID {pid}) — temporary target" for pid, executable in sorted(self.temporary_keys)]
        for rule in self.rules:
            if rule.is_process_specific:
                lines.append(f"{rule.executable} — matching process profile only")
            else:
                lines.append(f"{rule.executable} — all processes using this app")
        return sorted(lines, key=str.casefold)


def plan_removal(selected: Iterable[ProcessRow], temporary: TemporaryTargets) -> RemovalPlan:
    rows = list(selected)
    rules = {row.rule.key: row.rule for row in rows if row.rule is not None}
    temporary_keys = frozenset(key for key in map(target_key, rows) if key in temporary)
    return RemovalPlan(tuple(rules.values()), temporary_keys)
