@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :dependencies

where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher not found. Install Python 3.13 64-bit from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

py -3.13 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.13 was not found. Install Python 3.13 64-bit, then run this file again.
    pause
    exit /b 1
)

py -3.13 -c "import struct, sys; sys.exit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 (
    echo A 64-bit Python 3.13 installation is required.
    pause
    exit /b 1
)

echo Creating the project's virtual environment...
py -3.13 -m venv .venv
if errorlevel 1 goto :failed

:dependencies
rem Install only when requirements.txt differs from the copy saved after the
rem last successful install. Delete .venv to force a clean reinstall.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo Installing App Volume Manager dependencies...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :failed
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

if not exist ".venv\Scripts\pythonw.exe" (
    echo pythonw.exe was not found in the virtual environment. Try run-console.bat for details.
    goto :failed
)
start "" ".venv\Scripts\pythonw.exe" app.py %*
exit /b 0

:failed
echo.
echo Setup or startup failed. The error is shown above.
pause
exit /b 1
