# CS2 Integration

> id: `cs2-gsi` · version 1.0.0

Receives **Counter-Strike 2 Game State Integration** (GSI) and exposes it so a
[SignalRGB effect](../signalrgb-effect.md) can drive game-reactive lighting
(HP, low-HP pulse, flashbang white-out, bomb alarm, team tint).

## Why a companion plugin?

SignalRGB *device plugins* are sandboxed and can't open sockets. CS2 needs to
POST game state to a local HTTP endpoint. So SignalCompanion is the **network
receiver**, and a SignalRGB *effect* (ordinary web content, which can `fetch`
localhost) reads the state back out.

```
CS2  ──(GSI POST)──▶  SignalCompanion (cs2-gsi plugin, http://127.0.0.1:3000)
                                  │  serves GET /state (JSON, CORS-open)
                                  ▼
                      cs2_reactive.html  ──▶  SignalRGB canvas → your devices
```

## What the plugin does

- Runs a `ThreadingHTTPServer` (default `127.0.0.1:3000`).
- Accepts CS2's POSTs, validates the auth token, and parses the body into a
  flat, effect-friendly schema (`health`, `armor`, `flashed`, `bomb`, `team`,
  `round_phase`, `weapon`, `kills`, …).
- Serves the latest state as `GET /state` (CORS-open) for the effect.
- Publishes `cs2.state` on the EventBus for other plugins.
- A watchdog flips the state to `connected: false` if CS2 stops POSTing
  (game closed), so the lighting returns to idle.

## Setup

1. In **Settings → CS2 Integration**, click **Install CS2 GSI config…**. This
   writes `gamestate_integration_signalcompanion.cfg` into your CS2 `cfg`
   folder (auto-located via the Steam registry + `libraryfolders.vdf`, appid
   730). **Restart CS2** afterwards.
2. Install the bundled SignalRGB effect — see
   **[SignalRGB effect](../signalrgb-effect.md)**.
3. Make sure SignalCompanion is running, then launch CS2 and join a match.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Enable CS2 Game State receiver | on | Master switch. |
| Listen port | 3000 | Must match the port in the effect's properties. |
| Auth token | `signalcompanion` | Shared secret; written into the GSI cfg and checked on every POST. |

The tab shows the auto-located CS2 cfg folder and has the
**Install CS2 GSI config…** button. If auto-location fails, set
`plugins → cs2-gsi → cfg_dir` manually in `config.json`.

## Config keys

```json
"cs2-gsi": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 3000,
  "auth_token": "signalcompanion",
  "cfg_dir": ""
}
```

## The `/state` schema

`GET http://127.0.0.1:3000/state` returns the latest parsed state, e.g.:

```json
{
  "connected": true,
  "ts": 1718370000.0,
  "health": 100, "armor": 100, "helmet": true,
  "flashed": 0, "smoked": 0, "burning": 0,
  "round_kills": 0,
  "team": "CT", "activity": "playing",
  "round_phase": "live", "bomb": null,
  "map_phase": "live", "round": 4,
  "weapon": "weapon_ak47", "ammo_clip": 30, "ammo_reserve": 90,
  "kills": 7, "deaths": 3
}
```

When CS2 isn't connected (or after the idle watchdog fires), it returns
`{"connected": false, ...}`.

## Verification gate

!!! warning "Can a SignalRGB effect `fetch` localhost?"
    Device plugins are sandboxed without network; effects are ordinary web
    content and *most likely can* fetch. This is unconfirmed on your setup. If
    `http://127.0.0.1:3000/state` returns live JSON in a browser but the effect
    never reacts, the effect sandbox is blocking the `fetch` — switch the bridge
    transport (file-watch or WebSocket) **without changing the receiver**. See
    the [SignalRGB effect page](../signalrgb-effect.md#if-fetch-is-blocked).
