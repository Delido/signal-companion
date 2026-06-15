"""Locate the CS2 cfg folder and install the GSI config file.

CS2 reads `gamestate_integration_*.cfg` files from:
    <steam library>/steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/

We find Steam via the registry, parse libraryfolders.vdf to enumerate library
roots, and pick the one that actually contains CS2 (appid 730).
"""
import logging
import os
import re
from pathlib import Path

_CS2_REL = Path("steamapps") / "common" / "Counter-Strike Global Offensive" / "game" / "csgo" / "cfg"
_CFG_NAME = "gamestate_integration_signalcompanion.cfg"


def _steam_root():
    """Steam install dir from the registry (HKCU first, then HKLM)."""
    try:
        import winreg
    except ImportError:
        return None
    for hive, key, val in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                path, _ = winreg.QueryValueEx(k, val)
                if path and os.path.isdir(path):
                    return Path(path)
        except OSError:
            continue
    return None


def _library_roots(steam_root):
    """Parse libraryfolders.vdf for all Steam library paths (incl. steam_root)."""
    roots = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return roots
    # Each library entry has a "path" "<dir>" line.
    for m in re.finditer(r'"path"\s*"([^"]+)"', text):
        p = Path(m.group(1).replace("\\\\", "\\"))
        if p.is_dir() and p not in roots:
            roots.append(p)
    return roots


def locate_cs2_cfg_dir():
    """Return the CS2 cfg folder Path if found, else None."""
    steam = _steam_root()
    if not steam:
        return None
    for root in _library_roots(steam):
        candidate = root / _CS2_REL
        if candidate.is_dir():
            return candidate
    return None


def _cfg_contents(port, token):
    return (
        '"SignalCompanion CS2 Integration v1.1"\n'
        "{\n"
        f'    "uri"       "http://127.0.0.1:{port}"\n'
        '    "timeout"   "5.0"\n'
        '    "buffer"    "0.0"\n'
        '    "throttle"  "0.05"\n'
        '    "heartbeat" "10.0"\n'
        '    "auth"\n'
        "    {\n"
        f'        "token" "{token}"\n'
        "    }\n"
        '    "data"\n'
        "    {\n"
        '        "provider"            "1"\n'
        '        "map"                 "1"\n'
        '        "round"               "1"\n'
        '        "player_id"           "1"\n'
        '        "player_state"        "1"\n'
        '        "player_weapons"      "1"\n'
        '        "player_match_stats"  "1"\n'
        '        "bomb"                "1"\n'
        '        "phase_countdowns"    "1"\n'
        "    }\n"
        "}\n"
    )


def install_gsi_cfg(port=3000, token="signalcompanion", cfg_dir=None):
    """Write the GSI cfg into the CS2 cfg folder. `cfg_dir` overrides
    auto-location. Returns the written file path. Raises on failure."""
    target_dir = Path(cfg_dir) if cfg_dir else locate_cs2_cfg_dir()
    if not target_dir:
        raise RuntimeError("CS2 cfg folder not found; specify it manually.")
    target_dir = Path(target_dir)
    if not target_dir.is_dir():
        raise RuntimeError(f"Not a directory: {target_dir}")
    dest = target_dir / _CFG_NAME
    dest.write_text(_cfg_contents(port, token), encoding="utf-8")
    logging.info(f"[cs2] installed GSI cfg → {dest}")
    return dest


def uninstall_gsi_cfg(cfg_dir=None):
    """Remove the SignalCompanion GSI cfg. `cfg_dir` overrides auto-location.
    Returns the deleted path, or None if it wasn't there."""
    target_dir = Path(cfg_dir) if cfg_dir else locate_cs2_cfg_dir()
    if not target_dir:
        return None
    dest = Path(target_dir) / _CFG_NAME
    if dest.is_file():
        dest.unlink()
        logging.info(f"[cs2] removed GSI cfg → {dest}")
        return dest
    return None
