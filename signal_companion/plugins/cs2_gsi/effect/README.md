# CS2 Reactive — SignalRGB effect

Game-reactive lighting driven by SignalCompanion's CS2 GSI bridge.

## How it fits together

```
CS2  ──(GSI POST)──▶  SignalCompanion (cs2-gsi plugin, http://127.0.0.1:3000)
                                  │  serves GET /state (JSON, CORS-open)
                                  ▼
                      cs2_reactive.html  ──▶  SignalRGB canvas → your devices
```

SignalCompanion is the network receiver (SignalRGB device plugins are
sandboxed and can't open sockets). This effect is plain web content rendered
by SignalRGB, so it *can* `fetch` localhost — that's the bridge.

## Install

1. In SignalCompanion settings → **CS2 Integration** tab, click
   **Install CS2 GSI config…** (writes `gamestate_integration_signalcompanion.cfg`
   into your CS2 `cfg` folder). Restart CS2.
2. Copy `cs2_reactive.html` into your SignalRGB effects folder, typically:
   `Documents\WhirlwindFX\Effects\`  (or import via SignalRGB → Effects → Add).
3. Apply the **CS2 Reactive** effect to a layer in SignalRGB.
4. Make sure SignalCompanion is running. Launch CS2 and join a match.

## What it shows

| Situation        | Lighting                                   |
|------------------|--------------------------------------------|
| Idle / no match  | slow grey breathing                        |
| Alive            | green→red gradient by HP                   |
| HP ≤ 35          | red pulse, intensity scales as HP drops    |
| Flashbang        | white-out scaled by flash amount           |
| Bomb planted     | fast red alarm (overrides HP)              |
| Dead             | dim team tint (T amber / CT blue)          |

## Tuning

The effect exposes **Bridge port** (match the plugin's listen port, default
3000) and **Brightness** in SignalRGB's effect properties.

## Verification gate

If the lighting never reacts but `http://127.0.0.1:3000/state` returns live
JSON in a browser, SignalRGB's effect sandbox is blocking the `fetch`. In that
case switch the bridge transport (see the plugin's notes) — e.g. write state
to a file the effect reads, or a WebSocket — without changing the receiver.
