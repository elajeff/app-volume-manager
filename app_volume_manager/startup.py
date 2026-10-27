"""Current-user sign-in task, with migration from the former Run entry."""

import base64
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "AppVolumeManager"

# Use Windows' native task commands instead of comtypes' dynamic IDispatch
# wrapper, which can lose the underlying error when a scheduler call fails.
_TASK_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    $request = [System.Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String('__REQUEST__')) | ConvertFrom-Json
    if ($request.operation -eq 'enable') {
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $action = New-ScheduledTaskAction -Execute $request.executable `
            -Argument $request.arguments -WorkingDirectory $request.directory
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName $request.name -TaskPath '\' -Action $action `
            -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    } else {
        $task = Get-ScheduledTask -TaskPath '\' | Where-Object { $_.TaskName -eq $request.name }
        if ($request.operation -eq 'disable') {
            if ($null -ne $task) { $task | Unregister-ScheduledTask -Confirm:$false }
        } else {
            $enabled = $false
            if ($null -ne $task) {
                $actions = @($task.Actions)
                $triggers = @($task.Triggers | Where-Object {
                    $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' -and $_.Enabled
                })
                $enabled = [string]$task.State -ne 'Disabled' -and $actions.Count -eq 1 `
                    -and $actions[0].Execute -eq $request.executable `
                    -and $actions[0].Arguments -eq $request.arguments -and $triggers.Count -gt 0
            }
            Write-Output $enabled.ToString().ToLowerInvariant()
        }
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
'''


def _startup_parts() -> tuple[str, str, str]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        return str(executable), "--minimized", str(executable.parent)
    script = Path(sys.argv[0]).resolve()
    python_path = Path(sys.executable)
    pythonw_path = python_path.with_name("pythonw.exe")
    interpreter = pythonw_path if pythonw_path.exists() else python_path
    return str(interpreter), subprocess.list2cmdline([str(script), "--minimized"]), str(script.parent)


def _startup_command() -> str:
    executable, arguments, _directory = _startup_parts()
    return subprocess.list2cmdline([executable]) + " " + arguments


def _task_name() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    return "AppVolumeManager-" + (f"{domain}-{user}" if domain else user)


def _run_task_command(operation: str) -> str:
    executable, arguments, directory = _startup_parts()
    request = json.dumps({
        "operation": operation, "name": _task_name(),
        "executable": executable, "arguments": arguments, "directory": directory,
    })
    # Encoding keeps paths with quotes, spaces, or non-ASCII characters out of
    # PowerShell source syntax. No shell or execution-policy changes are needed.
    payload = base64.b64encode(request.encode("utf-8")).decode("ascii")
    script = _TASK_SCRIPT.replace("__REQUEST__", payload)
    encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("Windows startup command timed out after 20 seconds. Try again.") from exc
    if result.returncode:
        raise OSError(result.stderr.strip() or "Windows could not update the sign-in task.")
    return result.stdout.strip()


def _legacy_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
            return value == _startup_command()
    except FileNotFoundError:
        return False


def _remove_legacy() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_VALUE_NAME)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


def is_startup_enabled() -> bool:
    if os.name != "nt":
        return False
    return _run_task_command("query").casefold() == "true" or _legacy_enabled()


def set_startup_enabled(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Automatic startup is only supported on Windows.")
    _run_task_command("enable" if enabled else "disable")
    # Keep the existing launch method if registering its replacement failed.
    _remove_legacy()


def migrate_startup() -> None:
    """Upgrade an enabled legacy entry without enabling startup for other users."""
    if os.name == "nt" and _legacy_enabled():
        set_startup_enabled(True)
