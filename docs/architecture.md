# Architecture

SignalCompanion is a small **plugin platform**. The core knows nothing about
specific features; it discovers plugins, gives each one a set of services, and
builds the tray + settings UI from whatever it found.

## Big picture

```
                ┌──────────────────────────────────────────────┐
                │                  app.py (tray)               │
                │  builds icon + menu from loaded plugins      │
                └───────────────┬──────────────────────────────┘
                                │ uses
                ┌───────────────▼──────────────────────────────┐
                │            core/manager.py                    │
                │  discover() → seed config → start()/stop()    │
                │  per-plugin try/except isolation              │
                └───┬───────────────┬───────────────┬──────────┘
                    │ hands each     │               │
                    │ plugin a       │               │
                    ▼                ▼               ▼
            PluginContext      EventBus         devices registry
         (config, log, status, (pub/sub,        (USB IDs + protocol
          play_sound, events,   replay_last)     constants, read_battery)
          devices)
                    │
                    ▼
            plugins/<name>/  ── one package each, auto-discovered
```

## Core modules

| Module | Responsibility |
|---|---|
| `app.py` | Tray entry point. Builds the icon and menu **data-driven** from each plugin's `tray_status()` / `tray_menu_items()`. `--settings` spawns the UI as a subprocess and reloads config when it closes. |
| `core/plugin.py` | The `Plugin` base class + `PluginContext` dataclass (the services handed to each plugin). |
| `core/manager.py` | `PluginManager`: discovery, config seeding, lifecycle, and per-plugin error isolation. |
| `core/config.py` | Namespaced JSON config under `plugins.<id>`, recursive default-merging, and the legacy CorsairCompanion migration. |
| `core/events.py` | Thread-safe pub/sub `EventBus` with `replay_last` for late subscribers. |
| `core/devices.py` | The device registry (USB IDs + protocol constants), `read_battery()`, and UI dropdown helpers. See [Devices](devices.md). |
| `core/audio.py` | `play_sound(path)` via `winsound` (async, with a `MessageBeep` fallback). |
| `core/comutil.py` | `ensure_com_initialized()` — per-thread COM init, shared by both mic plugins (pycaw from worker threads). |
| `ui/settings_app.py` | Generic notebook: one tab per plugin via `build_settings_tab` / `save_settings`. No per-feature code. |

## The plugin contract

Every plugin is a package under `signal_companion/plugins/<name>/` exposing a
module-level `PLUGIN` instance (or a `get_plugin()` factory) of a `Plugin`
subclass.

```python
class Plugin:
    id: str          # kebab-case; also the config namespace
    name: str        # human label / settings tab title
    version: str
    description: str

    def default_config(self) -> dict: ...     # always include "enabled"

    def start(self, ctx: PluginContext): ...  # spin up threads/watchers
    def stop(self): ...                        # tear down; must be idempotent

    def build_settings_tab(self, parent, cfg_section) -> dict: ...
    def save_settings(self, cfg_section, vars): ...

    def tray_status(self) -> dict | None: ...  # optional
    def tray_menu_items(self) -> list: ...     # optional
```

Lifecycle, as run by the manager:

```
seed config from default_config()
start(ctx)        # spin up background work
   ... runs ...
stop()            # tear down
```

See [Writing a plugin](writing-a-plugin.md) for a complete, working example.

## PluginContext — the services a plugin gets

`start(ctx)` receives a `PluginContext` with everything a plugin is allowed to
touch:

| Service | What it does |
|---|---|
| `ctx.config()` | Live, namespaced config section for this plugin (reflects edits after a reload). |
| `ctx.events` | The shared `EventBus` — `publish(topic, data)` / `subscribe(topic, cb)`. |
| `ctx.devices` | The `core.devices` module (resolve devices, read battery, etc.). |
| `ctx.set_status({"label","color"})` | Update this plugin's tray indicator (or `None` to clear). |
| `ctx.play_sound(path)` | Play a `.wav` (or system beep when `path` is empty). |
| `ctx.log` | A `logging.Logger` named after the plugin id. |

Plugins **never import each other**. Cross-plugin communication happens only via
`ctx.events`. Topics currently in use:

| Topic | Publisher | Payload |
|---|---|---|
| `game_mode.active` | Game Mode | `bool` |
| `mic.muted` | Mic Mute Mirror | `bool` |
| `headset.battery` | Battery Alert | `int` percent |
| `cs2.state` | CS2 Integration | flat state dict |

## Error isolation

Discovery, `start()`, `stop()`, status callbacks and tray-menu building are each
wrapped in per-plugin `try/except`. A single broken plugin logs a traceback and
is skipped — it can't take down the tray or the other plugins.

## Process model

The tray runs in one process. The **settings dialog runs as a separate
process** (`--settings`), so tkinter owns its own main thread cleanly. When the
settings window closes, the tray reloads `config.json` from disk so live changes
take effect without a restart.
