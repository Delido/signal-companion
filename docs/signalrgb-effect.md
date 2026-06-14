# SignalRGB effect (CS2 Reactive)

The lighting half of the [CS2 Integration](plugins/cs2-integration.md) is a
SignalRGB **effect** — ordinary web content rendered by SignalRGB that reads the
companion's `/state` endpoint and paints a reactive colour onto a `<canvas>`.

It lives at `signal_companion/plugins/cs2_gsi/effect/cs2_reactive.html`.

!!! info "The canvas already exists"
    A common question: *"isn't the SignalRGB canvas still missing?"* — No. The
    bundled effect already contains a complete SignalRGB canvas
    (`<canvas id="exCanvas" width="320" height="200">`), uses SignalRGB's
    `engine.get(...)` property API, and declares its adjustable properties via
    `<meta property=...>` tags. It renders a single device-wide reactive colour.
    What's *not* yet confirmed is whether SignalRGB's effect sandbox allows the
    `fetch` to localhost (see [below](#if-fetch-is-blocked)) — that's the open
    item, not the canvas itself.

## How it's structured

```html
<meta property="port"       label="Bridge port" type="number" min="1" max="65535" default="3000">
<meta property="brightness" label="Brightness"  type="number" min="0" max="100"  default="100">
...
<canvas id="exCanvas" width="320" height="200"></canvas>
```

- The `<meta property>` tags become user-adjustable controls in SignalRGB's
  effect properties panel.
- `engine.get("port")` / `engine.get("brightness")` read those values at
  runtime; the effect falls back to defaults when opened in a plain browser, so
  you can preview it outside SignalRGB.
- A `requestAnimationFrame` loop polls `http://127.0.0.1:<port>/state` ~10×/s and
  fills the whole canvas with the colour for the current game state. SignalRGB
  samples that canvas onto your devices.

## What it shows

| Situation | Lighting |
|---|---|
| Idle / no match | slow grey breathing |
| Alive | green → red gradient by HP |
| HP ≤ 35 | red pulse, intensity scales as HP drops |
| Flashbang | white-out scaled by flash amount |
| Bomb planted | fast red alarm (overrides HP) |
| Dead | dim team tint (T amber / CT blue) |

## Install

The CS2 Integration settings tab installs the effect for you:

1. Set up the receiver first — see
   [CS2 Integration → Setup](plugins/cs2-integration.md#setup).
2. In **Settings → CS2 Integration**, under *2) SignalRGB effect*, click
   **Install effect to SignalRGB**. This copies `cs2_reactive.html` into your
   SignalRGB Effects folder (auto-located, honouring OneDrive/Documents
   redirection). **Uninstall** removes it again.
3. In SignalRGB, apply the **CS2 Reactive** effect to a layer.
4. Make sure SignalCompanion is running, launch CS2, join a match.

!!! note "Manual install still works"
    If you'd rather do it by hand, copy `cs2_reactive.html` into
    `Documents\WhirlwindFX\Effects\` or import it via **SignalRGB → Effects →
    Add**.

## Tuning

The effect exposes two properties in SignalRGB:

- **Bridge port** — must match the plugin's listen port (default 3000).
- **Brightness** — 0–100 scale applied to the output.

## If `fetch` is blocked { #if-fetch-is-blocked }

If `http://127.0.0.1:3000/state` returns live JSON in a browser **but the effect
never reacts**, SignalRGB's effect sandbox is blocking the `fetch`. The receiver
doesn't need to change — only the transport between it and the effect:

- **File watch** — have the plugin also write the latest state to a file the
  effect can read.
- **WebSocket** — expose the state over a WS the effect connects to.

Either swap is isolated to the bridge; the GSI parsing, schema and EventBus
publishing stay exactly as they are.

!!! tip "Keep the bridge dead simple"
    A sister project saw hard-to-tame race conditions with SignalRGB web content
    under WebView2. Prefer the simplest transport that works.
