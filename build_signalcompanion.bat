@echo off
REM Build SignalCompanion (tray app, windowed) as a ONEDIR folder.
REM Output: dist\SignalCompanion\SignalCompanion.exe (+ supporting files)
REM
REM Uses the spec so dynamically-imported plugins + data files are collected.
REM Onedir (not onefile) is friendlier to Microsoft Defender. Quit any running
REM tray instance first (PyInstaller can't overwrite a locked exe).

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
echo Built: %~dp0dist\SignalCompanion\SignalCompanion.exe
endlocal
