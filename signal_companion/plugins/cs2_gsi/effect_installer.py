"""Install / uninstall the bundled SignalRGB effect (cs2_reactive.html).

SignalRGB loads effects from the user's WhirlwindFX Effects folder. "Install"
copies the bundled effect there; "uninstall" removes it. Works both from source
and from the PyInstaller build — the files are collected as data files, and we
read them via the package's own location (falling back to importlib.resources).

SignalRGB shows a library thumbnail from a .png with the same base name as the
.html, so we install both files (without the .png the library shows a broken
image).
"""
import logging
import os
from pathlib import Path

_EFFECT_NAME = "cs2_reactive.html"
# All files that make up the installed effect. The .html is the primary one; the
# .png is SignalRGB's library preview. Missing files are skipped gracefully.
_EFFECT_FILES = ("cs2_reactive.html", "cs2_reactive.png")


def _documents_dir() -> Path:
    """The user's real Documents folder, honouring OneDrive/redirection via the
    Shell Folders registry entry; falls back to ~/Documents."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ) as k:
            val, _ = winreg.QueryValueEx(k, "Personal")
            if val:
                return Path(os.path.expandvars(val))
    except OSError:
        pass
    return Path(os.path.expanduser("~")) / "Documents"


def locate_effects_dir() -> Path:
    """SignalRGB's per-user Effects folder (may not exist yet)."""
    return _documents_dir() / "WhirlwindFX" / "Effects"


def _read_bundled(name) -> bytes:
    """Bytes of a bundled effect file, from the source tree or frozen bundle."""
    here = Path(__file__).resolve().parent / "effect" / name
    if here.is_file():
        return here.read_bytes()
    # Fallback for odd frozen layouts: read it as a package resource.
    from importlib import resources
    return (resources.files("signal_companion.plugins.cs2_gsi")
            .joinpath("effect", name).read_bytes())


def install_effect(effects_dir=None) -> Path:
    """Copy the bundled effect (html + preview png) into the SignalRGB Effects
    folder. `effects_dir` overrides auto-location. Returns the html path. Raises
    if the primary html can't be written."""
    target = Path(effects_dir) if effects_dir else locate_effects_dir()
    target.mkdir(parents=True, exist_ok=True)
    primary = target / _EFFECT_NAME
    for name in _EFFECT_FILES:
        try:
            data = _read_bundled(name)
        except Exception:
            if name == _EFFECT_NAME:
                raise            # the html is mandatory; the png is optional
            logging.warning(f"[cs2] bundled effect file missing, skipped: {name}")
            continue
        (target / name).write_bytes(data)
        logging.info(f"[cs2] installed effect file → {target / name}")
    return primary


def uninstall_effect(effects_dir=None):
    """Remove the installed effect files. Returns the deleted html path, or None
    if it wasn't there. Raises only on an actual delete error."""
    target = Path(effects_dir) if effects_dir else locate_effects_dir()
    removed_primary = None
    for name in _EFFECT_FILES:
        dest = target / name
        if dest.is_file():
            dest.unlink()
            logging.info(f"[cs2] removed effect file → {dest}")
            if name == _EFFECT_NAME:
                removed_primary = dest
    return removed_primary
