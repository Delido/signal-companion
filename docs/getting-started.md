# Getting started

SignalCompanion is a Windows tray application. You can run it from source
(Python) or as a single-file `.exe`.

## Requirements

- Windows 10 / 11
- Python 3.11+ (3.13 used for the official build) — only needed to run from
  source or build the exe
- The peripherals you want to drive (see [Devices](devices.md)). Plugins whose
  device isn't present simply stay inactive — nothing crashes.

## Install dependencies (from source)

```powershell
pip install -r signal_companion/requirements.txt
```

| Package | Used for |
|---|---|
| `pystray` | system tray icon |
| `Pillow` | tray icon rendering |
| `psutil` | process watching (Game Mode) |
| `pywinusb` | HID access (keyboard / headset) |
| `pycaw` | Windows audio endpoint control (mic mute / drift) |
| `comtypes` | COM bindings used by pycaw |
| `ttkbootstrap` | modern themed settings UI (falls back to plain `ttk` if absent) |

## Run from source

Run from the repository root (the folder that contains `signal_companion/`):

```powershell
# tray + all enabled plugins
python -m signal_companion

# settings dialog only (this is what the tray's "Settings…" menu spawns)
python -m signal_companion.app --settings
```

## Build the single-file exe

```powershell
build_signalcompanion.bat        # -> dist\SignalCompanion.exe
```

The batch file drives PyInstaller through `SignalCompanion.spec`, which collects
the dynamically-imported plugins and their data files. See
[Development & building](development.md) for the details and gotchas.

!!! tip "Quit before rebuilding"
    PyInstaller can't overwrite a locked exe. Quit any running tray instance
    (and close the settings window) before building.

## Configuration & logs

Everything lives in:

```
%APPDATA%\SignalCompanion\
  config.json     namespaced per-plugin settings
  watcher.log     runtime log (INFO and above)
```

On first run, an old `%APPDATA%\CorsairCompanion\config.json` is migrated into
the new per-plugin namespaces automatically (`game_mode` → `game-mode`,
`mic_mute_mirror` → `mic-mute-mirror`, `mic_drift_logger` → `mic-drift`).

## The settings UI

The settings window uses **ttkbootstrap** for a modern themed look, with a live
theme switcher in the header (your choice is persisted per user). If
ttkbootstrap isn't installed it transparently falls back to plain `ttk`.

Each plugin contributes exactly one tab — there is no hard-coded per-feature UI.
Most changes (enable/disable, intervals, thresholds) apply within a few seconds;
device-selection and port/transport changes apply on the next SignalCompanion
start (the settings dialog reminds you on Save).
