; Inno Setup script for SignalCompanion (onedir build).
;
; Packages dist\SignalCompanion\ (produced by build_signalcompanion.bat) into a
; single Setup .exe that installs to Program Files, adds Start Menu / optional
; Desktop shortcuts, an optional "run at Windows startup" entry, and a proper
; uninstaller. Build it with build_installer.bat (or open this in Inno Setup).
;
; Requires Inno Setup 6: https://jrsoftware.org/isdl.php

#define MyAppName "SignalCompanion"
#define MyAppVersion "2.1.1"
#define MyAppPublisher "Sebastian Mendyka"
#define MyAppURL "https://github.com/Delido/signal-companion"
#define MyAppExeName "SignalCompanion.exe"
; SourceDir can be overridden from the command line (ISCC /DSourceDir=...) so we
; can build from a temp dist outside OneDrive (which locks the in-repo dist).
#ifndef SourceDir
  #define SourceDir "..\dist\SignalCompanion"
#endif

[Setup]
; A unique, stable AppId — keep this constant across versions so upgrades work.
AppId={{A3F1C2E4-7B9D-4E6A-9C12-5D8E3F0A1B2C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Default to a per-user install (no UAC prompt): friendlier, Defender-quiet, and
; the HKCU autostart entry then belongs to the actual user. The user can still
; choose an all-users install (which elevates) from the dialog. With "lowest",
; {autopf} resolves to the per-user programs folder (%LOCALAPPDATA%\Programs).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=SignalCompanion-Setup-{#MyAppVersion}
SetupIconFile=..\assets\signalcompanion.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close a running tray instance before install/uninstall so files aren't locked.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Run SignalCompanion when Windows starts"; GroupDescription: "Startup:"

[Files]
; The entire onedir folder (exe + _internal\...). recursesubdirs pulls _internal.
Source: "{#SourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "{#MyAppExeName}"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Optional autostart for the current user (only if the "startup" task is ticked).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Nothing extra: user config + logs in %APPDATA%\SignalCompanion are intentionally
; left in place so a reinstall keeps your settings.
