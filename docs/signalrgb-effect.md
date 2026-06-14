# SignalRGB effect (CS2 Reactive)

The lighting half of the [CS2 Integration](plugins/cs2-integration.md) is a
SignalRGB **effect** — web content rendered by SignalRGB that reads the live CS2
state from SignalCompanion and paints reactive lighting onto a `<canvas>` which
SignalRGB samples across your devices.

It lives at `signal_companion/plugins/cs2_gsi/effect/cs2_reactive.html`.

## How the effect gets the data (the hard part)

SignalRGB runs effects in **Ultralight** (a WebKit engine) from a **public HTTPS
origin** (`https://signalrgbmarketplace.pages.dev/`), even for a local effect.
That sandbox blocks every obvious local transport — confirmed via the SignalRGB
console:

- `http://127.0.0.1` → **mixed-content blocked** (`was not allowed to display
  insecure content`),
- a self-signed `https://127.0.0.1` → **rejected** (Ultralight trusts only its
  own bundled `cacert.pem`, not the Windows store),
- `file://` and relative paths → blocked / resolve to the remote marketplace.

The stock **Weather effect** is the clue: it `fetch`es a *public* HTTPS API, so
effects *can* do HTTPS — just not to an untrusted localhost. So SignalCompanion
runs a small **HTTPS bridge** the effect can reach:

1. it generates a local CA + a `127.0.0.1` certificate (`cryptography`),
2. **appends the CA to Ultralight's `cacert.pem`** (`%LOCALAPPDATA%\VortxEngine\
   app-*\Signal-x64\cacert.pem` — user-writable, no admin; idempotent, keeps a
   `.bak`, re-applied on startup so SignalRGB updates that replace the bundle
   get re-trusted),
3. serves `GET/POST /state` over **HTTPS** with CORS + the Private-Network-Access
   header + `Cache-Control: no-store`,
4. the effect **POSTs** to `https://127.0.0.1:3443/state` (POST so Ultralight
   can't serve a cached/frozen response).

CS2 still POSTs its Game State to the plain-HTTP receiver on `:3000`; the effect
reads the HTTPS bridge on `:3443`. See [tls_bridge / receiver](plugins/cs2-integration.md).

!!! warning "One-time setup: restart SignalRGB once"
    After SignalCompanion first patches `cacert.pem`, **SignalRGB must be
    restarted once** so Ultralight reloads the bundle and trusts the bridge
    certificate. Until then the effect shows its idle colour and doesn't react.

## What it shows

Pure GSI data drives it (no screen capture):

| Situation | Lighting |
| --- | --- |
| No match / between rounds | gentle team-tinted (or cyan) breathing |
| Alive | HP gradient green (full) → red (low), brighter centre |
| HP ≤ 35 | red pulse on the edges |
| Kill | brief white flash |
| Flashbang | full white-out, fades with the flash amount |
| Smoke / molotov | desaturated / orange flicker |
| Bomb planted | red tick that **accelerates over the ~40 s C4 fuse** |
| Bomb exploded / defused | orange-white explosion / green defuse flash |
| Round won / lost | green / red flash |
| Dead | black closes in **from the edges to the centre**, then a faint spectating glow until respawn |

## Configuration (SignalRGB effect properties)

All adjustable in SignalRGB's effect panel:

- **Brightness**
- **Health bar (instead of full glow)** — switch to a positionable bar on black
  whose length tracks HP, with **Health bar color / X / Y / Width / Height**
- Individual toggles: **Low-HP edge pulse**, **Kill flash**, **Flashbang
  white-out**, **Smoke and molotov tints**, **Bomb tick and explosion**, **Round
  win / loss flash**, **Death fade to black**

## Install

1. Set up the receiver + GSI config first — see
   [CS2 Integration → Setup](plugins/cs2-integration.md#setup).
2. In **Settings → CS2 Integration**, under *2) SignalRGB effect*, click
   **Install effect to SignalRGB** (copies `cs2_reactive.html` + the
   `cs2_reactive.png` thumbnail into your SignalRGB Effects folder, auto-located
   honouring OneDrive/Documents redirection). **Uninstall** removes them.
3. **Restart SignalRGB once** (so it trusts the bridge cert — see the warning
   above), then apply the **CS2 Reactive** effect to a layer.
4. Make sure SignalCompanion is running, launch CS2, join a match.

!!! note "Effect HTML is cached hard"
    SignalRGB caches the effect HTML — a changed effect only loads after a full
    SignalRGB restart. The effect logs `CS2 Reactive vX.Y loaded` to the
    SignalRGB console so you can confirm which build is running.

## Effect implementation notes

Gotchas baked into the effect (for anyone editing it):

- **No `<!doctype>`/`<html>` wrapper** and the `<script>` after `</body>` — a
  doctype wrapper stops SignalRGB from activating the effect at all.
- **Start the render loop at top level**, not from `onEngineReady()` — current
  SignalRGB builds don't call it (matches SignalRGB's own Solid Color / Rainbow).
- **NaN-safe rendering** — one NaN in the smoothing once froze the canvas to
  black permanently while the loop kept running.
- Read `<meta property>` values as **injected globals** (`window.brightness`…),
  not `engine.get(...)`. Never put a bare `&` in a meta label (breaks the
  property parser).
