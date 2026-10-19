@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=py -3.13"

%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.13 64-bit is required. Install it from https://www.python.org/downloads/windows/
    goto :failed
)

%PYTHON% -c "import struct, sys; sys.exit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 (
    echo A 64-bit Python 3.13 installation is required.
    goto :failed
)

if not exist ".venv-build\Scripts\python.exe" (
    echo Creating the build environment...
    %PYTHON% -m venv .venv-build
    if errorlevel 1 goto :failed
)

".venv-build\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv-build\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :failed

echo.
echo Running tests...
".venv-build\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :failed

echo.
echo Building App Volume Manager.exe with the application icon...
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name "App Volume Manager" --icon "assets\app-icon.ico" --add-data "assets;assets" --collect-all pycaw --collect-all comtypes app.py
if errorlevel 1 goto :failed

if not exist "dist\App Volume Manager\App Volume Manager.exe" (
    echo Build command finished but App Volume Manager.exe was not found.
    goto :failed
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path 'dist\app volume manager.zip') { Remove-Item 'dist\app volume manager.zip' -Force }; Compress-Archive -Path 'dist\App Volume Manager' -DestinationPath 'dist\app volume manager.zip' -CompressionLevel Optimal"
if errorlevel 1 goto :failed

echo.
echo BUILD SUCCEEDED
echo Executable: dist\App Volume Manager\App Volume Manager.exe
echo Package:    dist\app volume manager.zip
echo Copy the entire App Volume Manager folder when distributing manually.
goto :done

:failed
echo.
echo BUILD FAILED. Review the error output above.
:done
echo.
pause
