# Writing a plugin

A plugin is a self-contained package that the manager discovers, configures,
starts and stops. You don't touch the core, the tray, or the settings UI — you
just drop a package in `plugins/` and restart.

## Minimal plugin

Create `signal_companion/plugins/<name>/__init__.py` exposing a module-level
`PLUGIN` instance of a `core.plugin.Plugin` subclass:

```python
from signal_companion.core.plugin import Plugin
import tkinter as tk
from tkinter import ttk


class MyPlugin(Plugin):
    id = "my-plugin"            # kebab-case; also the config namespace
    name = "My Plugin"          # settings tab title
    version = "1.0.0"
    description = "What it does, in one line."

    def default_config(self):
        return {"enabled": True, "interval": 5.0}

    def start(self, ctx):       # ctx: PluginContext
        self.ctx = ctx
        # ctx.config() -> live config section
        # ctx.events, ctx.devices, ctx.play_sound(path)
        # ctx.set_status({"label","color"}), ctx.log
        ...

    def stop(self):             # must be idempotent
        ...

    def build_settings_tab(self, parent, cfg):
        enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        ttk.Checkbutton(parent, text="Enable", variable=enabled).pack(anchor="w")
        return {"enabled": enabled}

    def save_settings(self, cfg, vars):
        cfg["enabled"] = bool(vars["enabled"].get())


PLUGIN = MyPlugin()
```

Drop the package in `plugins/`, restart — it's discovered automatically, its
config section is seeded from `default_config()`, and its tab appears in
Settings.

## The lifecycle in detail

| Step | Method | Notes |
|---|---|---|
| Discover | — | The manager imports your package and reads `PLUGIN`. |
| Seed config | `default_config()` | Merged into `config.json` under `plugins.<id>`. Always include `"enabled"`. |
| Start | `start(ctx)` | Spin up threads/watchers. Store `ctx`. Wrap your own work — exceptions here are caught and logged, but only your plugin is skipped. |
| Run | — | Your threads do the work; read fresh settings via `ctx.config()`. |
| Stop | `stop()` | Tear down threads/handles. Must be safe to call even if `start()` half-failed. |

!!! tip "Background work pattern"
    Every bundled plugin runs its work on a `threading.Thread(daemon=True)` with
    a `threading.Event` stop flag and a `self._stop.wait(interval)` loop that
    re-reads `ctx.config()` each tick. That gives you live settings and clean
    shutdown for free. Copy that shape.

## Using the services (`PluginContext`)

```python
def start(self, ctx):
    self.ctx = ctx

    # live config (reflects edits after the settings dialog closes)
    cfg = ctx.config()

    # log under your plugin id
    ctx.log.info("started")

    # tray indicator
    ctx.set_status({"label": "My Plugin: ok", "color": (90, 160, 90)})

    # play a sound (empty path -> system beep)
    ctx.play_sound(cfg.get("sound_path") or None)

    # cross-plugin messaging — never import other plugins
    ctx.events.subscribe("cs2.state", self._on_cs2)
    ctx.events.publish("my.topic", {"hello": "world"})

    # devices
    spec = ctx.devices.resolve_headset(cfg.get("device", "auto"))
```

See [Architecture → PluginContext](architecture.md#plugincontext-the-services-a-plugin-gets)
for the full service list and the EventBus topic table.

## Settings tab conventions

`build_settings_tab(parent, cfg)` builds tkinter widgets inside `parent` (a
`ttk.Frame`) and returns a dict of the tk variables. `save_settings(cfg, vars)`
writes them back **in place** into the config section. The framework handles
persisting `config.json` and reloading the running plugins.

For device dropdowns, reuse the registry helpers so your tab stays in sync with
[the device registry](devices.md):

```python
from signal_companion.core.devices import (
    headset_choices, choice_label_for_key, choice_key_for_label,
)
choices = headset_choices()
dev_var = tk.StringVar(value=choice_label_for_key(choices, cfg.get("device", "auto")))
# ... combobox with [label for _, label in choices] ...
# on save:
cfg["device"] = choice_key_for_label(choices, dev_var.get())
```

## Optional tray contributions

```python
def tray_status(self):
    return {"label": "My Plugin", "color": (90, 160, 90)}  # or None

def tray_menu_items(self):
    return [("Do the thing", self._do_thing)]
```

## Packaging for the frozen build

PyInstaller can't see dynamically-imported plugins by static analysis, so
`SignalCompanion.spec` collects the whole `signal_companion.plugins` subpackage
plus its data files.

- A **pure-Python** bundled plugin works in the frozen build with **no spec
  change**.
- A plugin with **non-Python data files** is covered by the existing
  `**/*.html | *.md | *.cfg` data glob (e.g. the CS2 effect). Other file types
  need a glob addition.

See [Development → building](development.md#building-the-exe) for the spec
details (including the `sys.path` fix that makes plugin collection work).
