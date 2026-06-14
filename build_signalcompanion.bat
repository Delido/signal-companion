@echo off
REM Build single-file SignalCompanion.exe (tray app, windowed).
REM Output: dist\SignalCompanion.exe
REM
REM Uses the spec so dynamically-imported plugins + the CS2 effect data files
REM are collected. Quit any running tray instance first (PyInstaller can't
REM overwrite a locked exe).

setlocal
cd /d "%~dp0"

set "PYI=%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\pyinstaller.exe"

if not exist "%PYI%" (
    echo Falling back to: python -m PyInstaller
    set "PYI=python -m PyInstaller"
)

%PYI% --noconfirm --clean SignalCompanion.spec

if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo.
echo Built: %~dp0dist\SignalCompanion.exe
endlocal
