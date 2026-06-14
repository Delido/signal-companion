# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller SignalCompanion.spec   (or run build.bat)
#
# Plugins are imported dynamically by core.manager, so PyInstaller can't see
# them by static analysis — collect the whole plugins subpackage plus its data
# files (the CS2 effect HTML + READMEs + battery sound).
#
# ONEDIR build (not onefile): a onefile exe self-extracts to a temp dir on every
# launch, which Microsoft Defender often flags / rescans. A onedir folder under
# Program Files is friendlier to Defender and faster to start. The Inno Setup
# installer (installer/SignalCompanion.iss) packages this folder.

import os
import sys

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ICON = os.path.join(SPECPATH, "assets", "signalcompanion.ico")
ICON = ICON if os.path.isfile(ICON) else None

# collect_submodules imports the package to enumerate it, and runs at spec-eval
# time — before Analysis applies `pathex`. So the repo root must be on sys.path
# now, or it silently finds nothing and the dynamically-imported plugins are
# left out of the build (empty Settings notebook, no plugins at runtime).
if SPECPATH not in sys.path:
    sys.path.insert(0, SPECPATH)

hiddenimports = collect_submodules("signal_companion.plugins")
assert len(hiddenimports) > 1, (
    "collect_submodules found no plugin submodules — repo root not importable "
    f"during build (got {hiddenimports!r})"
)
# ttkbootstrap is optional at runtime; include it if present so the themed UI
# works in the frozen build.
try:
    hiddenimports += collect_submodules("ttkbootstrap")
except Exception:
    pass

datas = collect_data_files("signal_companion.plugins", includes=["**/*.html", "**/*.md", "**/*.cfg", "**/*.wav", "**/*.png"])

a = Analysis(
    ['signalcompanion_main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],                       # onedir: binaries/datas go in COLLECT, not the exe
    exclude_binaries=True,
    name='SignalCompanion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SignalCompanion',
)
