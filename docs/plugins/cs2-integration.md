# CS2 Integration

> id: `cs2-gsi` · version 1.0.0

Receives **Counter-Strike 2 Game State Integration** (GSI) and exposes it so a
[SignalRGB effect](../signalrgb-effect.md) can drive game-reactive lighting
(HP, low-HP pulse, flashbang white-out, bomb alarm, team tint).

## Why a companion plugin?

SignalRGB *device plugins* are sandboxed and can't open sockets. CS2 needs to
POST game state to a local HTTP endpoint. So SignalCompanion is the **network
receiver**. Reading the state back into a SignalRGB *effect* turned out to be
the hard part: effects run from a **public HTTPS origin**, so they can't fetch
plain `http://localhost` (mixed-content blocked). The fix is a second, **HTTPS**
endpoint whose certificate SignalCompanion makes SignalRGB trust — the full
story is on the **[SignalRGB effect](../signalrgb-effect.md)** page.

```
CS2  ──(GSI POST :3000 http)──▶  SignalCompanion (cs2-gsi plugin)
                                       │  HTTP receiver  :3000  (CS2 → us)
                                       │  HTTPS bridge   :3443  (effect ← us)
                                       ▼
        cs2_reactive.html  ──(POST :3443 https)──▶  SignalRGB canvas → devices
```

## What the plugin does

- Runs a `ThreadingHTTPServer` on `127.0.0.1:3000` (plain HTTP) that **CS2**
  POSTs Game State to.
- Accepts CS2's POSTs, validates the auth token, and parses the body into a
  flat, effect-friendly schema (`health`, `armor`, `flashed`, `bomb`,
  `bomb_countdown`, `team`, `round_phase`, `weapon`, `kills`, `win_team`, …).
  The bomb fuse countdown is taken from the GSI `bomb` component when present and
  otherwise from the `phase_countdowns` block (`phase == "bomb"`), so the effect's
  bomb tick stays in sync with the real C4 even for a non-spectator client.
- Runs an **HTTPS bridge** on `127.0.0.1:3443` (`tls_bridge`) that serves the
  latest state on `GET/POST /state` (CORS-open, Private-Network-Access header,
  `Cache-Control: no-store`) — this is what the **effect** reads. On startup it
  generates a local CA + cert and appends the CA to SignalRGB's Ultralight
  `cacert.pem` so the effect trusts it (one-time SignalRGB restart needed).
- Publishes `cs2.state` on the EventBus for other plugins.
- A watchdog flips the state to `connected: false` if CS2 stops POSTing
  (game closed), so the lighting returns to idle.

## Setup

1. In **Settings → CS2 Integration**, under *1) CS2 integration config*, click
   **Install CS2 GSI config…**. This writes
   `gamestate_integration_signalcompanion.cfg` into your CS2 `cfg` folder
   (auto-located via the Steam registry + `libraryfolders.vdf`, appid 730).
   **Restart CS2** afterwards. (**Uninstall** removes the cfg again.)
2. Under *2) SignalRGB effect*, click **Install effect to SignalRGB** to copy
   the effect into your SignalRGB Effects folder — see
   **[SignalRGB effect](../signalrgb-effect.md)**. **Restart SignalRGB once**
   (so it trusts the HTTPS bridge certificate), then apply the *CS2 Reactive*
   effect to a layer in SignalRGB.
3. Make sure SignalCompanion is running, then launch CS2 and join a match.

## Settings

| Setting | Default | Notes |
| --- | --- | --- |
| Enable CS2 Game State receiver | on | Master switch. |
| Listen port | 3000 | HTTP port CS2 POSTs to (must match the GSI cfg). The HTTPS bridge the effect reads is fixed at 3443. |
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

The HTTPS bridge `https://127.0.0.1:3443/state` (and, for debugging,
`http://127.0.0.1:3000/state` in a browser) returns the latest parsed state,
e.g.:

```json
{
  "connected": true,
  "ts": 1718370000.0,
  "health": 100, "armor": 100, "helmet": true,
  "flashed": 0, "smoked": 0, "burning": 0,
  "round_kills": 0,
  "team": "CT", "activity": "playing",
  "round_phase": "live", "bomb": null,
  "bomb_countdown": null, "phase_ends_in": "84.6",
  "win_team": null,
  "map_phase": "live", "round": 4,
  "weapon": "weapon_ak47", "ammo_clip": 30, "ammo_reserve": 90,
  "kills": 7, "deaths": 3
}
```

When CS2 isn't connected (or after the idle watchdog fires), it returns
`{"connected": false, ...}`.

The effect **POSTs** to the HTTPS bridge (POST, not GET, so Ultralight can't
freeze a cached response). The browser GET above is only for sanity-checking the
receiver.

## Confirmed working

!!! success "The transport is solved"
    The effect reaching the bridge was the central problem and is **resolved**:
    plain `http://localhost` is mixed-content blocked from the effect's HTTPS
    origin, so SignalCompanion runs an HTTPS bridge whose CA it appends to
    SignalRGB's `cacert.pem`. After a one-time SignalRGB restart the effect
    reacts live. The mechanism is documented on the
    [SignalRGB effect page](../signalrgb-effect.md#how-the-effect-gets-the-data-the-hard-part).
