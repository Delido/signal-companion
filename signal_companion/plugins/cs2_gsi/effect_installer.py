"""Install / uninstall the bundled SignalRGB effect (cs2_reactive.html).

SignalRGB loads effects from the user's WhirlwindFX Effects folder. "Install"
copies the bundled effect there; "uninstall" removes it. Works both from source
and from the PyInstaller build — the html is collected as a data file, and we
read it via the package's own location (falling back to importlib.resources).
"""
import logging
import os
from pathlib import Path

_EFFECT_NAME = "cs2_reactive.html"


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


def _read_bundled_effect() -> bytes:
    """Bytes of the bundled effect html, from the source tree or frozen bundle."""
    here = Path(__file__).resolve().parent / "effect" / _EFFECT_NAME
    if here.is_file():
        return here.read_bytes()
    # Fallback for odd frozen layouts: read it as a package resource.
    from importlib import resources
    return (resources.files("signal_companion.plugins.cs2_gsi")
            .joinpath("effect", _EFFECT_NAME).read_bytes())


def install_effect(effects_dir=None) -> Path:
    """Copy the bundled effect into the SignalRGB Effects folder. `effects_dir`
    overrides auto-location. Returns the written path. Raises on failure."""
    target = Path(effects_dir) if effects_dir else locate_effects_dir()
    target.mkdir(parents=True, exist_ok=True)
    dest = target / _EFFECT_NAME
    dest.write_bytes(_read_bundled_effect())
    logging.info(f"[cs2] installed effect → {dest}")
    return dest


def uninstall_effect(effects_dir=None):
    """Remove the installed effect. Returns the deleted path, or None if it
    wasn't there. Raises only on an actual delete error."""
    target = Path(effects_dir) if effects_dir else locate_effects_dir()
    dest = target / _EFFECT_NAME
    if dest.is_file():
        dest.unlink()
        logging.info(f"[cs2] removed effect → {dest}")
        return dest
    return None
