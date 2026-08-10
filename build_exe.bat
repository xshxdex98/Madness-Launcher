@echo off
REM ---------------------------------------------------------------------------
REM Build the standalone Madness Launcher.
REM
REM Produces ONE file: dist\MadnessLauncher.exe - send that and nothing else.
REM It contains Python, Qt and the launcher. The recipient installs nothing.
REM
REM The intermediate build\ folder is deleted afterwards on purpose. It holds a
REM half-built executable with the same name that cannot run, and picking that
REM one up gives "Failed to load Python DLL ...\_internal\python310.dll".
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller || exit /b 1
)

echo Building (this takes a minute)...
python -m PyInstaller --noconfirm --clean madness_launcher.spec
if errorlevel 1 ( echo BUILD FAILED & pause & exit /b 1 )

if exist build rmdir /s /q build

if not exist "dist\MadnessLauncher.exe" (
    echo BUILD FAILED - dist\MadnessLauncher.exe was not produced
    pause & exit /b 1
)

echo.
echo   Built: dist\MadnessLauncher.exe
echo.
echo   Send that single file. Run it once yourself first - a windowed build
echo   cannot report a startup failure, it just fails to appear.
echo.
endlocal
