@echo off
REM Build the SignalCompanion Setup installer with Inno Setup 6.
REM Prereq: run build_signalcompanion.bat first (needs dist\SignalCompanion\).
REM Output: installer\Output\SignalCompanion-Setup-<version>.exe

setlocal
cd /d "%~dp0"

if not exist "dist\SignalCompanion\SignalCompanion.exe" (
    echo ERROR: dist\SignalCompanion\ not found. Run build_signalcompanion.bat first.
    exit /b 1
)

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo ERROR: Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
    echo        ^(or: winget install JRSoftware.InnoSetup^)
    exit /b 1
)

"%ISCC%" "installer\SignalCompanion.iss"
if errorlevel 1 (
    echo INSTALLER BUILD FAILED
    exit /b 1
)

echo.
echo Built: %~dp0installer\Output\SignalCompanion-Setup-2.2.0.exe
endlocal
