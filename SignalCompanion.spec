# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller SignalCompanion.spec   (or run build.bat)
#
# Plugins are imported dynamically by core.manager, so PyInstaller can't see
# them by static analysis — collect the whole plugins subpackage plus its data
# files (the CS2 effect HTML + READMEs).

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules("signal_companion.plugins")
# ttkbootstrap is optional at runtime; include it if present so the themed UI
# works in the frozen build.
try:
    hiddenimports += collect_submodules("ttkbootstrap")
except Exception:
    pass

datas = collect_data_files("signal_companion.plugins", includes=["**/*.html", "**/*.md", "**/*.cfg"])

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
    a.binaries,
    a.datas,
    [],
    name='SignalCompanion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
