"""Build process-instance rows from live Windows audio sessions and saved rules."""

from dataclasses import dataclass
from typing import Iterable

from app_volume_manager.rules import AppRule, resolve_rule
from app_volume_manager.volume_service import AudioSession


@dataclass(frozen=True)
class ProcessRow:
    """One live process instance, or a saved rule waiting for a matching session."""

    row_id: str
    executable: str
    process_id: int | None
    session_count: int
    current_volumes: tuple[int, ...]
    rule: AppRule | None
    active: bool
    process_signature: str | None = None
    process_role: str = "Unknown role"
    session_details: tuple[str, ...] = ()


def build_process_rows(
    sessions: Iterable[AudioSession], rules: Iterable[AppRule]
) -> list[ProcessRow]:
    """Group sessions by process ID, not just by executable name.

    A saved process-role rule takes precedence over an app-wide rule. Rows for
    closed processes remain visible so saved rules are easy to find and change.
    """
    rule_list = list(rules)
    app_rules = {rule.executable.casefold(): rule for rule in rule_list if not rule.is_process_specific}
    process_rules = {
        rule.process_signature: rule
        for rule in rule_list
        if rule.is_process_specific and rule.process_signature is not None
    }

    groups: dict[tuple[str, int | None, str], list[AudioSession]] = {}
    display_names: dict[tuple[str, int | None, str], str] = {}
    for session in sessions:
        executable_key = session.executable.casefold()
        process_id = session.process_id
        fallback = "" if process_id is not None else session.session_id
        key = (executable_key, process_id, fallback)
        groups.setdefault(key, []).append(session)
        display_names.setdefault(key, session.executable)

    rows: list[ProcessRow] = []
    active_executables: set[str] = set()
    active_signatures: set[str] = set()
    for (executable_key, process_id, fallback), grouped in groups.items():
        executable = display_names[(executable_key, process_id, fallback)]
        active_executables.add(executable_key)
        signatures = {item.process_signature for item in grouped if item.process_signature}
        signature = next(iter(signatures)) if len(signatures) == 1 else None
        if signature:
            active_signatures.add(signature)
        rule = resolve_rule(executable, signature, app_rules, process_rules)
        volumes = tuple(sorted({
            int(item.current_volume)
            for item in grouped
            if item.current_volume is not None
        }))
        roles = {item.process_role for item in grouped if item.process_role}
        role = next(iter(roles)) if len(roles) == 1 else "Multiple process roles"
        details = sorted({
            " — ".join(part for part in (item.session_name, item.device_name) if part)
            for item in grouped
            if item.session_name or item.device_name
        })
        identity = str(process_id) if process_id is not None else fallback
        rows.append(
            ProcessRow(
                row_id=f"process:{executable_key}:{identity}",
                executable=executable,
                process_id=process_id,
                session_count=len(grouped),
                current_volumes=volumes,
                rule=rule,
                active=True,
                process_signature=signature,
                process_role=role,
                session_details=tuple(details),
            )
        )

    for rule in rule_list:
        if rule.is_process_specific:
            if rule.process_signature in active_signatures:
                continue
            rows.append(
                ProcessRow(
                    row_id=f"rule:{rule.key}",
                    executable=rule.executable,
                    process_id=None,
                    session_count=0,
                    current_volumes=(),
                    rule=rule,
                    active=False,
                    process_signature=rule.process_signature,
                    process_role=rule.process_role or "Saved process role",
                )
            )
        elif rule.executable.casefold() not in active_executables:
            rows.append(
                ProcessRow(
                    row_id=f"rule:{rule.key}",
                    executable=rule.executable,
                    process_id=None,
                    session_count=0,
                    current_volumes=(),
                    rule=rule,
                    active=False,
                )
            )

    return sorted(
        rows,
        key=lambda row: (
            not row.active,
            row.executable.casefold(),
            row.process_id if row.process_id is not None else -1,
            row.process_role.casefold(),
        ),
    )
