# App Volume Manager

A Windows desktop utility for managing per-application audio-session volume with persistent rules, process-aware targeting, and low-overhead background monitoring.

I was tired of Discord's volume resetting itself to 100% and jumpscaring me every time I restarted my PC, so I figured I'd make this app.

## Features

- **Event-driven audio monitoring:** listens for Windows Core Audio session creation, volume changes, and playback-device changes. Applies matching rules as sessions appear and restores their saved volume if another app or the Windows mixer changes it. A slow safety scan covers missed notifications.
- **Process-aware volume control:** groups sessions by process ID, shows session counts and mixed volume values, and distinguishes separate instances of the same executable.
- **Persistent targeting rules:** supports executable-wide rules and process-role profiles when stable process details are available. If a process cannot be identified safely for reuse after restart, its selected volume remains temporary for that process instance.
- **Process search:** filters case-insensitively by executable, PID, audio session/device details, process role, and rule information. Checked processes remain selected while temporarily hidden by a search.
- **Live volume adjustment:** applies a target volume to checked processes and can save a reusable rule. The slider is disabled until a process is selected.
- **Customizable slider color:** defaults to bright blue (`#1677FF`) in both themes. The color editor supports a palette, live preview, editable RGB and HEX values, click-to-lock selection, and **Reset to default**. The chosen color is also used for both process-list scrollbars.
- **Desktop integration:** supports light and dark themes, a system-tray menu, and optional launch at Windows sign-in. Hidden mode keeps monitoring for new sessions without refreshing the full process list every two seconds.
- **Safer local settings:** rules and appearance preferences are stored outside the project directory under `%LOCALAPPDATA%\AppVolumeManager\` and are written atomically.

## Requirements

- Windows 10 or Windows 11
- 64-bit Python 3.13 for running from source or building the executable

## Run on Windows

1. Extract the project folder and double-click `run.bat`. On first launch, it creates a virtual environment and installs the required packages.
2. Processes appear after Windows creates an audio session for them, usually when an app starts playing audio. Use **Refresh list** if needed.
3. Use **Search processes** to narrow the list by app name, PID, session/device, role, or rule details. **Clear** or press **Esc** to remove the filter. Filtering does not clear previously checked processes; the selected count remains visible.
4. Click a row or its checkbox to select or deselect a process. Set **Volume for selected**, then choose **Apply to selected** to adjust the checked targets.
5. Choose **Add rule for app…** to save a rule for all processes with one executable name. Process-role rules are created when the app can safely distinguish a matching process profile; ambiguous targets remain temporary rather than being persisted too broadly.
6. Use **Remove selected** to remove saved rules and temporary targets associated with checked rows. It does not reset the current Windows audio volume.
7. Use **Slider color…** to preview a color. Move over the palette or hue strip to preview; click to hold a selected point while moving to the dialog buttons. Enter RGB channel values (`0`–`255`) or a `#RRGGBB` HEX value directly. **Reset to default** previews blue; choose **Save color** to persist it, or **Cancel** to restore the original color.
8. Choose **Light** or **Dark** from the Appearance menu. Enable **Start with Windows** to launch through a per-user sign-in task with no configured delay. Existing enabled registry startup entries are migrated when this version runs. Closing the window normally hides it in the system tray; select **Exit** from the tray menu to stop the app.

## How rules and monitoring work

An app-wide rule affects all audio sessions whose executable matches. A process-role profile is more specific and takes precedence when it matches. If stable process details are unavailable, a checked process can receive a temporary PID-scoped target for the current run instead of creating a persistent rule that might affect the wrong process later.

When the window is visible, the process table refreshes every two seconds. In the system tray, the app listens for Core Audio notifications and uses a slow safety scan. If notification registration is unavailable, it falls back to a five-second scan. Enabled rules enforce their configured volume. Changes made by an application or the Windows volume mixer are restored after a volume-change notification; scans also correct mismatches. Matching volumes are left alone. To change the target, use this app; to stop enforcing it, remove or disable the saved rule. Temporary process targets survive audio-session gaps and output-device changes while the same process is running. They expire when that process exits or the manager restarts, and **Remove selected** can cancel them.

At launch, saved volumes are applied before the interface and tray are built. Only one copy runs per Windows session; opening another copy brings up the existing window. Startup checks and changes run in the background with a 20-second limit per Windows command; the checkbox shows Checking or Updating until they finish. Startup warnings do not block a hidden launch and are shown in the app status. The sign-in task runs as the current user, without elevation, including on battery power. It improves launch timing but cannot guarantee starting before Discord or another sign-in application.

Windows only exposes controllable per-application volume after an audio session exists, so no user-space utility can guarantee changing an app's volume before its very first audio sample. If two sounds share the same Windows audio session, they cannot be controlled separately. Exclusive-mode audio and unusual device routing may also limit session control.

If saved rules cannot be loaded, the original file is preserved and rule saving is blocked. Repair or rename `%LOCALAPPDATA%\AppVolumeManager\settings.json`, then restart the app before saving new rules.

## Run tests

Double-click `test.bat`, or run from the project root:

```powershell
py -3.13 -m unittest discover -s tests -v
```

Tests cover volume-rule application, process targeting, session monitoring, settings persistence, search and selection, and key GUI interactions. They use simulated sessions and do not change real Windows audio settings; GUI tests are skipped where a display is unavailable. Core Audio timing and device behavior still need testing on Windows.

## Build a Windows executable

Install Python 3.13 64-bit, then double-click `build-windows.bat`. The script runs the tests and creates:

- `dist\App Volume Manager\App Volume Manager.exe`
- `dist\app volume manager.zip`

Keep the full **App Volume Manager** folder together when distributing it manually. Move it to a stable location before enabling startup because the sign-in entry records the executable path.

## Project structure

- `app.py` — application controller, process table, search, tray integration, and user actions.
- `app_volume_manager/color_utils.py` and `slider_color_dialog.py` — validated color conversion and the self-contained slider color editor.
- `app_volume_manager/audio_backend.py` — Windows audio-session discovery and volume control through Pycaw.
- `app_volume_manager/audio_monitor.py` — Core Audio session-created notifications, device registration, and retry behavior.
- `app_volume_manager/process_identity.py` — identifies reusable process profiles from stable command-line details.
- `app_volume_manager/process_list.py` — combines active sessions and saved rules into process rows.
- `app_volume_manager/volume_service.py` — applies persistent rules and temporary process-instance targets.
- `app_volume_manager/rules.py` and `settings.py` — rule validation, preference migration, and atomic JSON storage.
- `app_volume_manager/startup.py` — per-user sign-in task and legacy startup migration.
- `app_volume_manager/single_instance.py` — prevents competing copies and opens the existing window.
- `assets/` — window, taskbar, tray, and executable icons; `tests/` — automated regression suite.

The app does not require administrator privileges. It controls per-application audio sessions, not Windows master volume.
