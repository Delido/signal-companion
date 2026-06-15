# Audio Output Switcher

> id: `audio-router` · version 1.0.0

Knows every playback device on the machine and exposes a tiny **local HTTP
endpoint** so a SignalRGB macro (or anything that can open a URL / run `curl`)
can rotate the Windows default output device — e.g. flip **headset ↔ speakers**
with a single key.

## Why a companion plugin?

SignalRGB can bind a key to a macro, but its plugin sandbox can't change the
Windows default audio device. SignalCompanion can (via the Windows audio API),
so it offers the switch as a URL the macro calls.

```text
SignalRGB macro key ──(GET /next)──▶  SignalCompanion (audio-router :3010)
                                              │  IPolicyConfig.SetDefaultEndpoint
                                              ▼
                                    Windows default playback device
```

## What the plugin does

- Enumerates the **active render (playback) endpoints** via the MMDevice API
  (pycaw).
- Sets the default endpoint for all three roles (Console / Multimedia /
  Communications) via the undocumented **`IPolicyConfig`** COM interface — the
  same mechanism nircmd / SoundVolumeView / EarTrumpet use. There is no public
  API for this.
- Runs a `ThreadingHTTPServer` on `127.0.0.1:3010` with the endpoints below.
- Shows the current output device in the tray and publishes `audio.default` on
  the EventBus when it changes.

## Endpoints

`http://127.0.0.1:3010` (CORS-open, `Cache-Control: no-store`):

| Endpoint | Action |
| --- | --- |
| `GET /next` | Rotate to the **next** device in the configured rotation (this is the one to bind to a macro). |
| `GET /prev` | Rotate to the previous one. |
| `GET /set?name=X` | Switch to the active device whose name contains `X` (case-insensitive). |
| `GET /set?id=...` | Switch to a specific endpoint id. |
| `GET /set?i=N` | Switch to rotation member `N` (0-based). |
| `GET /current` | Report the current default device. |
| `GET /devices` | List active playback devices + rotation membership. |

All responses are JSON, e.g. `{"ok": true, "current": {"id": "…", "name": "…"}}`.

## Setup

1. In **Settings → Audio Output Switcher**, tick the devices `/next` should
   cycle through (in order). ● marks the current Windows default; a
   disconnected-but-configured device stays listed as *(not connected)* and is
   simply skipped while absent. Use **Test: switch to next now** to try it.
2. Trigger the switch with either:
   - **A URL** — bind a key in **SignalRGB** to a macro that opens
     `http://127.0.0.1:3010/next` (or `curl`, a browser bookmark, a Stream Deck
     button — anything that issues an HTTP GET), or
   - **The no-window exe argument** — run `SignalCompanion.exe --audio-switch`
     (below), for launchers that run a *program* rather than a URL.

## No-window trigger: `SignalCompanion.exe --audio-switch`

Some launchers (SignalRGB's *Run Application*, Stream Deck, a desktop shortcut)
run a program rather than open a URL. For those, run **the already-installed,
trusted `SignalCompanion.exe`** with an argument — it opens **no window**, asks
the running tray to switch, and exits:

```text
Application:  C:\Users\<you>\AppData\Local\Programs\SignalCompanion\SignalCompanion.exe
Arguments:    --audio-switch
```

- Default rotates (`/next`); pass an action for others:
  `--audio-switch prev`, `--audio-switch "set?name=Speakers"`.
- In **Settings → Audio Output Switcher**, the exact application path +
  arguments are shown, and **Create 'Audio Switch' shortcut on Desktop** makes a
  ready-to-bind `.lnk` that runs with no window.

!!! note "Why not a separate little helper exe?"
    An earlier build shipped a standalone `AudioSwitch.exe`, but a *onefile*
    PyInstaller helper self-extracts on every launch and is unsigned — exactly
    what Defender/SmartScreen tend to block when another app (SignalRGB) starts
    it. Reusing the main **onedir** `SignalCompanion.exe` (which launchers run
    fine, just like any installed program) avoids that entirely.

## Toast notification

When **Show a notification (toast) on each switch** is enabled (default), every
switch — from the URL *or* the `--audio-switch` argument — pops a short Windows
toast with the new device name (e.g. *Audio output — Kopfhörer (… Virtuoso XT
…)*), shown via SignalCompanion's tray icon. Untick it in the Settings tab for
silent switching.

!!! tip "Two devices = a toggle"
    With exactly two devices ticked, `/next` simply flips between them — the
    classic headset ↔ speakers toggle. With three or more it cycles in order.

## Settings

| Setting | Default | Notes |
| --- | --- | --- |
| Enable Audio Output Switcher | on | Master switch. |
| Endpoint port | 3010 | Port the local HTTP endpoint listens on. |
| Devices in rotation | *(none)* | Ordered endpoint ids `/next` cycles through. Empty = cycle **all** active devices. |

## Config keys

```json
"audio-router": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 3010,
  "devices": [
    "{0.0.0.00000000}.{…headset…}",
    "{0.0.0.00000000}.{…speakers…}"
  ]
}
```

`devices` stores **endpoint ids** (stable across reboots), not names, so the
rotation survives a device being renamed. Pick them in the Settings tab rather
than by hand.

## Notes

- Only **active** endpoints take part; a powered-off or unplugged device is
  skipped until it's back, so the rotation never lands on a dead output.
- The switch covers all three endpoint roles, so apps that follow the
  *Communications* device (Discord, Teams) move too.
