# Plugins

SignalCompanion ships with five bundled plugins. Each is a self-contained
package under `signal_companion/plugins/<name>/`, auto-discovered at startup,
with its config section seeded and its settings tab added automatically.

| Plugin | id | Version | Device needed |
|---|---|---|---|
| [Game Mode](game-mode.md) | `game-mode` | 2.0.0 | Supported keyboard |
| [Mic Mute Mirror](mic-mute-mirror.md) | `mic-mute-mirror` | 2.0.0 | Supported headset |
| [Mic Drift Logger](mic-drift.md) | `mic-drift` | 2.0.0 | Any Windows mic |
| [Battery Alert](battery-alert.md) | `battery-alert` | 1.0.0 | Battery-capable headset |
| [CS2 Integration](cs2-integration.md) | `cs2-gsi` | 1.0.0 | — (network + a SignalRGB effect) |

A plugin whose device isn't present stays inactive and logs why — it never
crashes the app. The first three plugins are near-verbatim migrations of the old
CorsairCompanion `feature_*.py` modules; Battery Alert and CS2 Integration are
new.

Want to add your own? See [Writing a plugin](../writing-a-plugin.md).
