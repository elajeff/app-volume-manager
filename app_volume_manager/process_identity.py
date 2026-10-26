"""Create repeatable labels for common multi-process desktop applications."""

from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Sequence

_ROLE_SWITCHES = {
    "--type": "type",
    "--utility-sub-type": "subtype",
    "--service-sandbox-type": "sandbox",
    "--app-user-model-id": "app-id",
}


def identify_process_role(
    executable: str, command_line: Sequence[str] | None
) -> tuple[str | None, str]:
    """Return a rule signature and readable role from stable process arguments.

    Electron/Chromium apps often launch several processes with the same .exe.
    Their stable ``--type`` and utility subtype switches distinguish main,
    renderer, GPU, and utility processes. We deliberately ignore volatile PID,
    renderer-client, timing, and tracing arguments.

    A role profile applies to every running process with the same executable
    name and role. It is not a promise to identify one transient PID forever.
    """
    if not command_line:
        return None, "Role unavailable"

    values: dict[str, str] = {}
    index = 1  # cmdline[0] is the executable path
    while index < len(command_line):
        argument = str(command_line[index])
        for switch, key in _ROLE_SWITCHES.items():
            if argument.casefold().startswith(switch + "="):
                values[key] = argument.split("=", 1)[1].strip().casefold()
                break
            if argument.casefold() == switch and index + 1 < len(command_line):
                values[key] = str(command_line[index + 1]).strip().casefold()
                index += 1
                break
        index += 1

    process_type = values.get("type")
    if process_type:
        parts = [f"type={process_type}"]
        for key in ("subtype", "sandbox", "app-id"):
            if values.get(key):
                parts.append(f"{key}={values[key]}")
        role_key = ";".join(parts)
        if process_type == "utility" and values.get("subtype"):
            label = f"Utility: {values['subtype']}"
        else:
            label = process_type.replace("-", " ").title() + " process"
        if values.get("sandbox"):
            label += f" ({values['sandbox']})"
    else:
        # Apps launched with only an executable path have a stable main-process
        # role. Apps with unrecognized extra arguments cannot be safely profiled.
        if len(command_line) > 1:
            return None, "Other process (not safely identifiable)"
        role_key = "main"
        label = "Main process"

    executable_key = PureWindowsPath(executable).name.casefold()
    if not executable_key:
        return None, label
    return f"{executable_key}|{role_key}", label
