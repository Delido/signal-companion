r"""Namespaced JSON config for SignalCompanion.

Layout (`%APPDATA%\SignalCompanion\config.json`):

    {
      "app": { "theme": "darkly", "autostart": false },
      "plugins": {
        "<plugin-id>": { ... plugin's own config ... },
        ...
      }
    }

Each plugin owns `plugins[<id>]`, seeded from its `default_config()`. The
recursive `_merge_defaults` (carried over from the old CorsairCompanion
config) means new keys appear after upgrades without wiping user values.

A one-time migration pulls the three legacy CorsairCompanion sections into
the new per-plugin namespaces on first run.
"""
import json
import logging
import os
from pathlib import Path

APP_NAME = "SignalCompanion"
CONFIG_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
LOG_PATH = CONFIG_DIR / "watcher.log"

# Old app, for one-time migration of existing user config.
_LEGACY_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "CorsairCompanion"
_LEGACY_PATH = _LEGACY_DIR / "config.json"

# Top-level (non-plugin) defaults. Plugin sections are filled in by the
# manager from each plugin's default_config() — see seed_plugin_defaults().
APP_DEFAULTS = {
    "app": {
        "theme": "darkly",          # ttkbootstrap theme name
    },
    "plugins": {},
}

# Maps legacy CorsairCompanion top-level section -> new plugin id.
_LEGACY_SECTION_TO_PLUGIN = {
    "game_mode": "game-mode",
    "mic_mute_mirror": "mic-mute-mirror",
    "mic_drift_logger": "mic-drift",
}


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = _deep_copy(APP_DEFAULTS)
        migrated = _migrate_legacy()
        if migrated:
            cfg["plugins"].update(migrated)
            logging.info(f"[config] migrated legacy CorsairCompanion config "
                         f"({', '.join(migrated)})")
        save_config(cfg)
        return cfg
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        merged = _merge_defaults(cfg, APP_DEFAULTS)
        merged.setdefault("plugins", {})
        return merged
    except Exception:
        logging.exception("[config] load failed; using defaults")
        return _deep_copy(APP_DEFAULTS)


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def seed_plugin_defaults(cfg, plugin_id, defaults):
    """Ensure cfg['plugins'][plugin_id] exists and contains all default keys.
    Returns the (possibly newly created) section. Mutates `cfg` in place."""
    section = cfg.setdefault("plugins", {}).get(plugin_id)
    if section is None:
        section = _deep_copy(defaults)
    else:
        section = _merge_defaults(section, defaults)
    cfg["plugins"][plugin_id] = section
    return section


def _migrate_legacy():
    """Read an old CorsairCompanion config.json and return a dict of
    {plugin_id: section} for the three legacy features. Empty if none."""
    if not _LEGACY_PATH.exists():
        return {}
    try:
        with open(_LEGACY_PATH, "r", encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        logging.exception("[config] legacy migration read failed")
        return {}
    out = {}
    for legacy_key, plugin_id in _LEGACY_SECTION_TO_PLUGIN.items():
        if isinstance(old.get(legacy_key), dict):
            out[plugin_id] = _deep_copy(old[legacy_key])
    return out


def _deep_copy(d):
    return json.loads(json.dumps(d))


def _merge_defaults(cfg, defaults):
    """Recursive merge: every default key is present; user values win for
    keys that exist in both; unknown user keys are preserved."""
    if not isinstance(cfg, dict):
        return _deep_copy(defaults)
    out = {}
    for k, default_v in defaults.items():
        cur = cfg.get(k, default_v)
        if isinstance(default_v, dict):
            out[k] = _merge_defaults(cur if isinstance(cur, dict) else {}, default_v)
        else:
            out[k] = cur
    for k, v in cfg.items():
        if k not in out:
            out[k] = v
    return out
