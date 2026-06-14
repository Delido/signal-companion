"""Plugin contract for SignalCompanion.

A plugin is a self-contained package under `signal_companion/plugins/<name>/`
that exposes a module-level `PLUGIN` instance (or a `get_plugin()` factory)
of a `Plugin` subclass. The manager discovers, configures, starts and stops
plugins; plugins never import each other directly — they communicate via the
EventBus on their `PluginContext`.

Lifecycle:
    manager seeds config from default_config()
    manager calls start(ctx)        # spin up threads/watchers
    ... runs ...
    manager calls stop()            # tear down

Settings UI:
    build_settings_tab(parent, cfg_section) -> vars   # build the tkinter tab
    save_settings(cfg_section, vars)                   # write vars back in place

Tray (optional):
    tray_status() -> {"label": str, "color": (r,g,b)} | None
    tray_menu_items() -> [(label, callback), ...]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class PluginContext:
    """Shared services handed to a plugin at start(). One per plugin."""
    plugin_id: str
    events: object                          # core.events.EventBus
    devices: object                         # core.devices module
    _get_section: Callable[[], dict]        # live, namespaced config getter
    _set_status: Callable[[str, dict], None]  # (plugin_id, status) -> refresh tray
    _play_sound: Callable[..., bool]

    log: logging.Logger = field(default=None)

    def __post_init__(self):
        if self.log is None:
            self.log = logging.getLogger(self.plugin_id)

    def config(self) -> dict:
        """Current config section for this plugin (reflects live edits)."""
        return self._get_section()

    def set_status(self, status: dict | None):
        """Update this plugin's tray indicator. `status` is
        {"label": str, "color": (r,g,b)} or None to clear."""
        self._set_status(self.plugin_id, status)

    def play_sound(self, path=None) -> bool:
        return self._play_sound(path)


class Plugin:
    """Base class for SignalCompanion plugins. Subclasses set the metadata
    class attributes and override the lifecycle / UI methods they need."""

    # ── metadata (override in subclass) ──
    id: str = "unnamed-plugin"           # kebab-case; config namespace
    name: str = "Unnamed Plugin"         # human label / settings tab title
    version: str = "1.0.0"
    description: str = ""

    def default_config(self) -> dict:
        """Default config section. Always include an "enabled" key."""
        return {"enabled": True}

    # ── lifecycle ──
    def start(self, ctx: PluginContext):
        """Spin up background work. Store ctx for later use."""

    def stop(self):
        """Tear down threads / handles. Must be idempotent."""

    # ── settings UI (tkinter; same idiom as the old per-feature tabs) ──
    def build_settings_tab(self, parent, cfg_section) -> dict:
        """Build widgets inside `parent` (a ttk.Frame). Return a dict of the
        tk variables / widgets needed by save_settings()."""
        return {}

    def save_settings(self, cfg_section, vars: dict):
        """Write UI state from `vars` back into `cfg_section` (in place)."""

    # ── tray (optional) ──
    def tray_status(self) -> dict | None:
        """Return {"label": str, "color": (r,g,b)} for the tray, or None."""
        return None

    def tray_menu_items(self):
        """Return [(label, callback), ...] to add to the tray menu."""
        return []
