@echo off
REM ---------------------------------------------------------------------------
REM Run Madness Launcher from source. This needs Python and PySide6 installed,
REM so it is for development. To hand the launcher to someone else, build the
REM standalone version with build_exe.bat - it bundles Python and Qt, and the
REM person you give it to installs nothing.
REM
REM This deliberately does NOT use pythonw. pythonw has no console, so a missing
REM dependency produces an error nobody ever sees and the launcher simply
REM "does nothing" - which is exactly how this went wrong in the wild.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python was not found on this computer.
    echo.
    echo   This script runs the launcher from source, which needs Python.
    echo   If you were given the launcher to play games with, you want the
    echo   standalone MadnessLauncher.exe instead - it needs nothing installed.
    echo.
    pause
    exit /b 1
)

python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python is installed, but PySide6 is not.
    echo.
    echo   Install it with:
    echo       python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

python -m madness_launcher
if errorlevel 1 (
    echo.
    echo   The launcher exited with an error. The message above says why.
    echo.
    pause
)
endlocal
