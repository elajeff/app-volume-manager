"""Testable audio-session models and volume-rule application logic."""

from dataclasses import dataclass
import threading
from typing import Callable, Iterable

from app_volume_manager.rules import AppRule, normalize_executable_name


@dataclass
class AudioSession:
    executable: str
    session_id: str
    set_volume: Callable[[int], None]
    process_id: int | None = None
    current_volume: int | None = None
    process_signature: str | None = None
    process_role: str = "Unknown role"
    session_name: str = ""
    device_name: str = ""

    def __post_init__(self) -> None:
        self.executable = normalize_executable_name(self.executable)
        self.session_id = str(self.session_id)
        if self.process_signature:
            self.process_signature = self.process_signature.casefold()


@dataclass(frozen=True)
class ScanResult:
    session_count: int
    matched_applications: frozenset[str]
    applied_count: int
    errors: tuple[str, ...]


class VolumeRuleEngine:
    """Prefer specific process-role rules, then fall back to app-wide rules."""

    def __init__(self) -> None:
        self._last_applied: dict[tuple[str, str], int] = {}
        self._lock = threading.RLock()

    def reset(self) -> None:
        with self._lock:
            self._last_applied.clear()

    @staticmethod
    def _prepare_rules(rules: Iterable[AppRule]):
        enabled_rules = [rule for rule in rules if rule.enabled]
        app_rules = {
            rule.executable.casefold(): rule
            for rule in enabled_rules
            if not rule.is_process_specific
        }
        process_rules = {
            rule.process_signature: rule
            for rule in enabled_rules
            if rule.is_process_specific
        }
        return app_rules, process_rules

    @staticmethod
    def _target_for_session(
        session: AudioSession,
        app_rules: dict[str, AppRule],
        process_rules: dict[str, AppRule],
        temporary_targets: dict[tuple[int, str], int] | None,
    ) -> int | None:
        app_key = session.executable.casefold()
        if session.process_id is not None and temporary_targets is not None:
            temporary = temporary_targets.get((session.process_id, app_key))
            if temporary is not None:
                return temporary

        rule = process_rules.get(session.process_signature) if session.process_signature else None
        if rule is None:
            rule = app_rules.get(app_key)
        return rule.volume if rule is not None else None

    def apply_new_session(
        self,
        session: AudioSession,
        rules: Iterable[AppRule],
        temporary_targets: dict[tuple[int, str], int] | None = None,
    ) -> ScanResult:
        """Apply a rule in the session-created callback without sweeping other sessions."""
        with self._lock:
            app_rules, process_rules = self._prepare_rules(rules)
            session_key = (session.executable.casefold(), session.session_id)
            target = self._target_for_session(session, app_rules, process_rules, temporary_targets)
            if target is None:
                self._last_applied.pop(session_key, None)
                return ScanResult(1, frozenset(), 0, ())

            matched = frozenset({session.executable})
            if self._last_applied.get(session_key) == target:
                return ScanResult(1, matched, 0, ())
            try:
                session.set_volume(target)
                self._last_applied[session_key] = target
                return ScanResult(1, matched, 1, ())
            except Exception as exc:
                return ScanResult(1, matched, 0, (
                    f"{session.executable} (session {session.session_id}): {exc}",
                ))

    def scan(
        self,
        sessions: Iterable[AudioSession],
        rules: Iterable[AppRule],
        force: bool = False,
        temporary_targets: dict[tuple[int, str], int] | None = None,
    ) -> ScanResult:
        with self._lock:
            app_rules, process_rules = self._prepare_rules(rules)
            current_keys: set[tuple[str, str]] = set()
            matched: set[str] = set()
            applied = 0
            errors: list[str] = []
            session_list = list(sessions)

            for session in session_list:
                app_key = session.executable.casefold()
                session_key = (app_key, session.session_id)
                current_keys.add(session_key)
                target = self._target_for_session(session, app_rules, process_rules, temporary_targets)
                if target is None:
                    self._last_applied.pop(session_key, None)
                    continue

                matched.add(session.executable)
                previous_target = self._last_applied.get(session_key)
                if not force and previous_target == target:
                    continue
                try:
                    session.set_volume(target)
                    self._last_applied[session_key] = target
                    applied += 1
                except Exception as exc:
                    errors.append(f"{session.executable} (session {session.session_id}): {exc}")

            for old_key in list(self._last_applied):
                if old_key not in current_keys:
                    self._last_applied.pop(old_key, None)

            return ScanResult(
                session_count=len(session_list),
                matched_applications=frozenset(matched),
                applied_count=applied,
                errors=tuple(errors),
            )
