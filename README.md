# App Volume Manager

Sets the volume of individual Windows apps and keeps it there.

I was tired of Discord's volume resetting itself to 100% and jumpscaring me every time I restarted my PC, so I figured I'd make this app.

## What it does

- Saves a volume for an app and applies it every time that app starts playing audio. If the app or the Windows volume mixer changes it later, it is set back.
- Handles apps that run several processes with the same .exe, such as Electron and Chromium apps. A rule can target one process role (for example the main process) instead of every process. When a process can't be told apart reliably, the volume you set applies to that process only until it exits.
- Runs in the system tray and reacts to Windows audio notifications instead of polling. A slow background rescan catches anything a notification missed.
- Optional start at sign-in, light and dark themes, and a custom slider color.

## Requirements

- Windows 10 or 11
- 64-bit Python 3.13 to run from source or build the executable

## Running it

Double-click `run.bat`. The first run creates a virtual environment in `.venv` and installs the dependencies; later runs start straight away and only reinstall when `requirements.txt` changes. If the app doesn't start, `run-console.bat` runs it with a console window so you can see the error.

Only one copy runs at a time. Starting it again brings up the existing window.

## Using it

- An app shows up in the list once Windows creates an audio session for it, which usually happens when it first plays sound. **Refresh list** rescans.
- Click rows to tick them, set **Volume for selected**, then **Apply to selected**. If the app can be identified reliably, this saves a rule; otherwise the volume applies until that process exits.
- **Add rule for app…** saves a rule for every process of one executable, whether or not it's running.
- **Remove selected** deletes the saved rules and temporary volumes of the ticked rows. It doesn't change the current volume.
- **Search processes** filters by name, PID, device, role or rule. Ticked rows stay ticked while hidden by the search.
- Closing the window hides it to the tray. Use **Exit** in the tray menu to quit.

A process-role rule wins over a rule for the whole app when both match.

## Start with Windows

Ticking **Start with Windows** registers a scheduled task for your user account that starts the app hidden in the tray when you sign in. It needs no administrator rights, runs at normal priority and also starts on battery. The task stores the path to `app.py` (or the .exe), so move the folder to where it will stay before turning this on.

Startup entries from older versions, either a registry Run value or a task at Task Scheduler's default low priority, are updated automatically. The app can't guarantee it starts before Discord or other sign-in apps.

## Limitations

Windows only lets apps change another app's volume once that app has an audio session, so the very first sound an app plays can't be adjusted in advance. Sounds that share one Windows audio session can't be controlled separately, and exclusive-mode audio may not be controllable at all.

## Settings and logs

Everything is stored in `%LOCALAPPDATA%\AppVolumeManager\`:

- `settings.json`: saved rules
- `preferences.json`: theme and slider color
- `app.log`: warnings and errors (up to about 200 KB, with one backup)

If `settings.json` can't be read, the file is left as it is and saving rules is blocked until you repair or rename it and restart the app.

## Tests

Run `test.bat`, or from the project root:

```powershell
py -3.13 -m unittest discover -s tests -v
```

The tests use simulated audio sessions and don't change real volumes. GUI tests are skipped when no display is available; one integration test registers and removes a temporary scheduled task. GitHub Actions runs the tests and `ruff check .` on every push and pull request. Install `requirements-dev.txt` to run ruff locally.

## Building the executable

Run `build-windows.bat`. It runs the tests and produces:

- `dist\App Volume Manager\App Volume Manager.exe`
- `dist\app volume manager.zip`

Keep the whole `App Volume Manager` folder together when copying it elsewhere.

## Project layout

- `app.py`: entry point. It stays in the project root because the sign-in task and `run.bat` start it by name.
- `app_volume_manager/audio_backend.py`: lists audio sessions and sets their volume through Pycaw.
- `app_volume_manager/audio_monitor.py`: Core Audio notifications for new sessions, volume changes and devices.
- `app_volume_manager/volume_service.py`: applies rules and temporary volumes to sessions.
- `app_volume_manager/rules.py`, `settings.py`: rule validation and the JSON settings files.
- `app_volume_manager/process_identity.py`: tells apart processes that share an executable.
- `app_volume_manager/process_list.py`: turns sessions and rules into table rows.
- `app_volume_manager/selection.py`: decides what applying or removing a volume changes.
- `app_volume_manager/startup.py`: the sign-in task.
- `app_volume_manager/single_instance.py`: keeps a single copy running.
- `app_volume_manager/ui/`: the main window, process table, dialogs, theme, tray icon and Win32 window calls.
- `assets/`: icons. `tests/`: the test suite.

The app controls per-app audio sessions, not the Windows master volume.
