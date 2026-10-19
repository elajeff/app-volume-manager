@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m unittest discover -s tests -v
) else (
    py -3.13 -m unittest discover -s tests -v
)
if errorlevel 1 (
    echo Tests failed.
    pause
    exit /b 1
)
echo.
echo Tests passed.
pause
