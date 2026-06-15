# SignalCompanion

**Extensible tray companion for SignalRGB.** It does what the SignalRGB plugin
sandbox can't: talk to the Windows audio API, watch processes, receive network
data (game integrations), and write directly to peripherals — while SignalRGB
keeps owning the lighting channel.

SignalCompanion is the successor to *CorsairCompanion* — same job, rebuilt as a
**drop-in plugin platform**. Existing CorsairCompanion config is migrated
automatically on first run.

---

## Why it exists

SignalRGB *device plugins* run as JavaScript in a restricted sandbox:

- no general network / sockets,
- no Windows Audio API,
- no process watching,
- limited, unreliable UI property write-back.

Anything that needs the operating system, the network, or coordination across
devices has to live **outside** that sandbox. That's SignalCompanion: a small
Windows tray app that runs alongside SignalRGB (and iCUE) and fills exactly
those gaps, while leaving the actual lighting to SignalRGB.

## What's in the box

| Plugin | id | What it does |
|---|---|---|
| [Game Mode](plugins/game-mode.md) | `game-mode` | Toggles keyboard hardware Game Mode when a whitelisted process runs. |
| [Mic Mute Mirror](plugins/mic-mute-mirror.md) | `mic-mute-mirror` | Bidirectional sync: headset mute button ↔ Windows default mic. |
| [Mic Drift Logger](plugins/mic-drift.md) | `mic-drift` | Diagnostic logging of unexpected mic volume / registry drift. |
| [Battery Alert](plugins/battery-alert.md) | `battery-alert` | Plays a sound when the headset battery drops below a threshold. |
| [Audio Output Switcher](plugins/audio-router.md) | `audio-router` | Local URL endpoint to rotate the default output device (headset ↔ speakers) from a SignalRGB macro. |
| [CS2 Integration](plugins/cs2-integration.md) | `cs2-gsi` | Receives CS2 Game State and feeds a [SignalRGB effect](signalrgb-effect.md). |

## How it's built

SignalCompanion is a **plugin platform**, not a fixed feature set. The tray
icon, menu and settings dialog are all built from whatever plugins are
discovered at startup — there is no per-feature wiring in the core. Adding a
capability is dropping a package in `plugins/`; see
[Writing a plugin](writing-a-plugin.md).

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

See [Architecture](architecture.md) for the full picture.

## Next steps

- New here? Start with **[Getting started](getting-started.md)**.
- Want to extend it? **[Writing a plugin](writing-a-plugin.md)**.
- Building the exe or hacking on protocols? **[Development & building](development.md)**.
