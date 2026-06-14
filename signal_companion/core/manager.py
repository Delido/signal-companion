"""Plugin discovery, configuration and lifecycle.

Discovers packages under `signal_companion.plugins`, instantiates each one's
`PLUGIN` (or `get_plugin()`), seeds its config, and manages start/stop with
per-plugin error isolation so a single broken plugin can't take down the tray.

Works both from source and from a PyInstaller build (see build.bat — the
plugins subpackage must be collected).
"""
import importlib
import logging
import pkgutil

from . import config as config_mod
from . import audio
from . import devices as devices_mod
from .events import EventBus
from .plugin import Plugin, PluginContext


class PluginManager:
    def __init__(self, status_callback=None):
        """`status_callback(plugin_id, status)` is invoked when a plugin
        updates its tray status; the tray app supplies it."""
        self.events = EventBus()
        self._status_callback = status_callback or (lambda pid, st: None)
        self.cfg = config_mod.load_config()
        self.plugins = []          # list[Plugin] in discovery order
        self._contexts = {}        # plugin_id -> PluginContext
        self.statuses = {}         # plugin_id -> status dict (for tray)

    # ── discovery ──
    def discover(self):
        import signal_companion.plugins as plugins_pkg

        for mod_info in pkgutil.iter_modules(plugins_pkg.__path__):
            if mod_info.name.startswith("_"):
                continue
            full = f"signal_companion.plugins.{mod_info.name}"
            try:
                module = importlib.import_module(full)
                plugin = self._instantiate(module)
                if plugin is None:
                    logging.warning(f"[manager] {full}: no PLUGIN / get_plugin(); skipped")
                    continue
                config_mod.seed_plugin_defaults(self.cfg, plugin.id, plugin.default_config())
                self.plugins.append(plugin)
                logging.info(f"[manager] loaded plugin '{plugin.id}' ({plugin.name} v{plugin.version})")
            except Exception:
                logging.exception(f"[manager] failed to load plugin module {full}")
        config_mod.save_config(self.cfg)
        return self.plugins

    @staticmethod
    def _instantiate(module):
        obj = getattr(module, "PLUGIN", None)
        if obj is None and hasattr(module, "get_plugin"):
            obj = module.get_plugin()
        if obj is None:
            return None
        plugin = obj() if isinstance(obj, type) else obj
        return plugin if isinstance(plugin, Plugin) else None

    # ── config access ──
    def reload_config(self):
        """Re-read config from disk (settings UI runs in a separate process)."""
        self.cfg = config_mod.load_config()
        for p in self.plugins:
            config_mod.seed_plugin_defaults(self.cfg, p.id, p.default_config())

    def _section_getter(self, plugin_id):
        # Always read through self.cfg, which reload_config() swaps wholesale —
        # plugins calling ctx.config() see live edits after a reload.
        def getter():
            return self.cfg.get("plugins", {}).get(plugin_id, {})
        return getter

    # ── lifecycle ──
    def start_all(self):
        for plugin in self.plugins:
            ctx = PluginContext(
                plugin_id=plugin.id,
                events=self.events,
                devices=devices_mod,
                _get_section=self._section_getter(plugin.id),
                _set_status=self._on_status,
                _play_sound=audio.play_sound,
            )
            self._contexts[plugin.id] = ctx
            try:
                plugin.start(ctx)
            except Exception:
                logging.exception(f"[manager] plugin '{plugin.id}' start() failed")

    def stop_all(self):
        for plugin in self.plugins:
            try:
                plugin.stop()
            except Exception:
                logging.exception(f"[manager] plugin '{plugin.id}' stop() failed")

    def _on_status(self, plugin_id, status):
        if status is None:
            self.statuses.pop(plugin_id, None)
        else:
            self.statuses[plugin_id] = status
        try:
            self._status_callback(plugin_id, status)
        except Exception:
            logging.exception("[manager] status callback failed")
