# Game Mode

> id: `game-mode` · version 2.0.0

Watches running Windows processes and toggles the keyboard's **hardware Game
Mode** over USB whenever any whitelisted executable is running.

## What it does

- Polls the process list on an interval (default 2 s).
- If any whitelisted process name matches, it sends the hardware Game Mode
  command to the keyboard's command interface — but only on state *transitions*
  (it doesn't spam writes).
- Publishes `game_mode.active` (`bool`) on the EventBus and updates the tray
  indicator (red dot = ON).

This is the hardware toggle, separate from SignalRGB's own Game Mode handling.
SignalRGB's plugin polls the keyboard (`syncGameModeFromHardware`) and picks the
change up within ~3 s, then runs its dependency chain (polling rate, FlashTap,
lighting refresh). Both processes share the HID device cleanly, so there's no
conflict.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Enable Game Mode auto-toggle | on | Master switch. |
| Keyboard | Auto-detect | Pick a specific [supported keyboard](../devices.md), `Auto-detect`, or `Disabled`. |
| Executables | *(empty)* | Process names that trigger Game Mode. Case-insensitive, exact match on process name (e.g. `cs2.exe`). |
| Poll interval (seconds) | 2.0 | Minimum 0.5 s. |

The settings tab lets you add executables manually **or pick from currently
running processes**, and remove entries.

## Config keys

```json
"game-mode": {
  "enabled": true,
  "device": "auto",
  "poll_interval_seconds": 2.0,
  "executables": []
}
```

## How the write works

The plugin opens the keyboard's command HID interface (matched by
`usage_page` / `usage` from the [device registry](../devices.md)) and sends:

```
report-id 0x00 | 00 01 02 01 E1 00 <0|1>
```

— the same wire bytes as the SignalRGB plugin's `setHardwareGameMode`. The
handle auto-reopens if the device disappears (USB reset, plugin reload).

## Troubleshooting

- **Nothing toggles** — check the log (`watcher.log`) for
  `keyboard: none (Game Mode inactive)`: the configured keyboard wasn't found.
- **Toggles but SignalRGB doesn't react** — that's SignalRGB's polling latency
  (~3 s) plus its own Game Mode chain; unrelated to this plugin.
