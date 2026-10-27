"""Testable audio-session models and volume-rule application logic."""

from dataclasses import dataclass
from typing import Callable, Iterable

from app_volume_manager.rules import AppRule, normalize_executable_name, resolve_rule


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

    @staticmethod
    def _prepare_rules(rules: Iterable[AppRule]):
        rule_list = list(rules)
        app_rules = {
            rule.executable.casefold(): rule
            for rule in rule_list
            if not rule.is_process_specific
        }
        process_rules = {
            rule.process_signature: rule
            for rule in rule_list
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

        rule = resolve_rule(session.executable, session.process_signature, app_rules, process_rules)
        return rule.volume if rule is not None and rule.enabled else None

    def apply_new_session(
        self,
        session: AudioSession,
        rules: Iterable[AppRule],
        temporary_targets: dict[tuple[int, str], int] | None = None,
    ) -> ScanResult:
        """Apply a rule in the session-created callback without sweeping other sessions."""
        return self.scan([session], rules, temporary_targets=temporary_targets)

    def scan(
        self,
        sessions: Iterable[AudioSession],
        rules: Iterable[AppRule],
        force: bool = False,
        temporary_targets: dict[tuple[int, str], int] | None = None,
    ) -> ScanResult:
        app_rules, process_rules = self._prepare_rules(rules)
        matched: set[str] = set()
        applied = 0
        errors: list[str] = []
        session_list = list(sessions)

        for session in session_list:
            target = self._target_for_session(session, app_rules, process_rules, temporary_targets)
            if target is None:
                continue

            matched.add(session.executable)
            if not force and session.current_volume == target:
                continue
            try:
                session.set_volume(target)
                session.current_volume = target
                applied += 1
            except Exception as exc:
                errors.append(f"{session.executable} (session {session.session_id}): {exc}")

        return ScanResult(
            session_count=len(session_list),
            matched_applications=frozenset(matched),
            applied_count=applied,
            errors=tuple(errors),
        )
