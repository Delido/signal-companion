# SignalCompanion

Extensible tray companion for SignalRGB. It does what the SignalRGB plugin
sandbox can't: talk to the Windows audio API, watch processes, receive network
data (game integrations), and write directly to peripherals while SignalRGB
owns the lighting channel.

Successor to *CorsairCompanion* — same job, but rebuilt as a **drop-in plugin
platform**. Existing config is migrated automatically on first run.

## Run

```
# install deps once
pip install -r signal_companion/requirements.txt

# from source (cwd = repo root, the folder containing signal_companion/)
python -m signal_companion            # tray + all enabled plugins
python -m signal_companion.app --settings   # settings dialog only

# build a single-file exe
build_signalcompanion.bat             # → dist\SignalCompanion.exe
```

The settings UI uses **ttkbootstrap** for a modern themed look with a live
theme switcher (header dropdown, persisted per user). If ttkbootstrap isn't
installed it transparently falls back to plain ttk.

Config + log live in `%APPDATA%\SignalCompanion\`.

## Bundled plugins

| Plugin              | id                 | What it does |
|---------------------|--------------------|--------------|
| Game Mode           | `game-mode`        | Toggles keyboard hardware Game Mode when a whitelisted process runs. |
| Mic Mute Mirror     | `mic-mute-mirror`  | Bidirectional sync: headset mute button ↔ Windows default mic. |
| Mic Drift Logger    | `mic-drift`        | Diagnostic logging of unexpected mic volume/registry drift. |
| Battery Alert       | `battery-alert`    | Plays a sound when headset battery drops below a threshold. |
| CS2 Integration     | `cs2-gsi`          | Receives CS2 Game State and feeds a SignalRGB effect (see `plugins/cs2_gsi/effect/`). |

## Architecture

```
app.py            tray entry; builds icon/menu from loaded plugins
core/
  plugin.py       Plugin ABC + PluginContext (services handed to each plugin)
  manager.py      discovery (plugins/ package), lifecycle, error isolation
  config.py       namespaced JSON config + legacy migration
  events.py       thread-safe pub/sub EventBus
  devices.py      device registry (USB IDs + protocol constants) + read_battery
  audio.py        sound playback
  comutil.py      per-thread COM init (pycaw from worker threads)
ui/settings_app.py  generic notebook; one tab per plugin, no per-feature code
plugins/<name>/   one package per plugin, auto-discovered
```

## Writing a plugin

Create `signal_companion/plugins/<name>/__init__.py` exposing a module-level
`PLUGIN` instance of a `core.plugin.Plugin` subclass:

```python
from signal_companion.core.plugin import Plugin
import tkinter as tk
from tkinter import ttk

class MyPlugin(Plugin):
    id = "my-plugin"            # kebab-case; config namespace
    name = "My Plugin"
    version = "1.0.0"

    def default_config(self):
        return {"enabled": True, "interval": 5.0}

    def start(self, ctx):       # ctx: PluginContext
        self.ctx = ctx
        # ctx.config() -> live config section, ctx.events, ctx.devices,
        # ctx.play_sound(path), ctx.set_status({"label","color"}), ctx.log
        ...

    def stop(self):
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
config section is seeded, and its tab appears in Settings. Plugins never import
each other; communicate via `ctx.events` (e.g. publish `headset.battery`,
subscribe to `cs2.state`).

> Note: PyInstaller can't see dynamically-imported plugins, so the spec
> collects the whole `signal_companion.plugins` subpackage and its data files.
> A new bundled plugin works in the frozen build with no spec change; a plugin
> with non-Python data files (like the CS2 effect) is covered by the existing
> `**/*.html|*.md|*.cfg` data glob.

## dev_probes/

One-shot HID/audio diagnostic scripts used to reverse-engineer the protocols
(`probe_battery.py` confirms the battery read framing before the Battery Alert
plugin relies on it). Not part of the shipped app.
