"""CS2 Game State Integration plugin (NEW).

CS2 ships game state to a local HTTP endpoint via a
`gamestate_integration_*.cfg` file. SignalRGB *device plugins* are sandboxed
without network, so this companion plugin is the receiver: it runs a small
HTTP server that
  - accepts the POSTs from CS2 (parses health/armor/flash/bomb/round/etc.),
  - serves the latest parsed state as JSON on GET /state (CORS-open) so a
    SignalRGB *effect* (web content, which can fetch localhost) can render
    game-reactive lighting, and
  - publishes `cs2.state` on the EventBus for other plugins.

See effect/ for the bundled SignalRGB effect and README for install steps.
"""
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from signal_companion.core import config as config_mod
from signal_companion.core.plugin import Plugin
from . import tls_bridge
from .cfg_installer import install_gsi_cfg, uninstall_gsi_cfg, locate_cs2_cfg_dir
from .effect_installer import install_effect, uninstall_effect, locate_effects_dir

# The SignalRGB effect runs in Ultralight from a public https origin and can't
# reach plain-HTTP localhost. tls_bridge serves /state over HTTPS (CA trusted
# via Ultralight's cacert.pem + Private Network Access header) so the effect can
# read it. CS2 itself still POSTs to the plain-HTTP receiver below.

# Shared latest-state, guarded by a lock. The HTTP handler writes it from the
# server thread; GET /state and the EventBus publish read it.
_state_lock = threading.Lock()
_latest_state = {"connected": False, "ts": 0}


def _snapshot_state():
    with _state_lock:
        return dict(_latest_state)


def _parse_gsi(payload):
    """Map a raw CS2 GSI POST body to our flat, effect-friendly schema."""
    player = payload.get("player") or {}
    pstate = player.get("state") or {}
    rnd = payload.get("round") or {}
    mp = payload.get("map") or {}
    stats = player.get("match_stats") or {}
    bomb = payload.get("bomb") or {}              # CS2 bomb component (state + countdown)
    pc = payload.get("phase_countdowns") or {}

    # Exact fuse time remaining (seconds) once planted — the only reliable way to
    # keep the tick in sync with the real C4. bomb.countdown is the cleanest source
    # but CS2 only sends it to spectator/GOTV clients; for a playing client the
    # round phase countdown carries it instead (phase=="bomb" → phase_ends_in is
    # the fuse, phase=="defuse" → defuse time). Prefer bomb.countdown, fall back.
    def _to_float(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    bomb_cd = _to_float(bomb.get("countdown"))
    if bomb_cd is None and pc.get("phase") == "bomb":
        bomb_cd = _to_float(pc.get("phase_ends_in"))

    weapon_name, clip, reserve = None, None, None
    for w in (player.get("weapons") or {}).values():
        if w.get("state") == "active":
            weapon_name = w.get("name")
            clip = w.get("ammo_clip")
            reserve = w.get("ammo_reserve")
            break

    return {
        "connected": True,
        "ts": time.time(),
        "health": pstate.get("health"),
        "armor": pstate.get("armor"),
        "helmet": pstate.get("helmet"),
        "flashed": pstate.get("flashed", 0),       # 0..255
        "smoked": pstate.get("smoked", 0),
        "burning": pstate.get("burning", 0),
        "round_kills": pstate.get("round_kills"),
        "team": player.get("team"),                # "T" / "CT"
        "activity": player.get("activity"),        # "playing"/"menu"/...
        "round_phase": rnd.get("phase"),           # freezetime/live/over
        # bomb component is finer-grained (planting/planted/defusing/defused/
        # exploded); fall back to round.bomb when the component isn't present.
        "bomb": bomb.get("state") or rnd.get("bomb"),
        "bomb_countdown": bomb_cd,                  # seconds left on the fuse, or None
        "phase_ends_in": pc.get("phase_ends_in"),   # seconds left in current phase
        "win_team": rnd.get("win_team"),           # "T"/"CT" when round is over
        "map_phase": mp.get("phase"),
        "round": mp.get("round"),
        "weapon": weapon_name,
        "ammo_clip": clip,
        "ammo_reserve": reserve,
        "kills": stats.get("kills"),
        "deaths": stats.get("deaths"),
    }


class _Handler(BaseHTTPRequestHandler):
    auth_token = "signalcompanion"
    on_state = None          # set by the plugin: callable(state) for EventBus

    def log_message(self, *args):
        pass                 # silence default stderr access log

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_GET(self):
        if self.path.startswith("/state"):
            with _state_lock:
                body = json.dumps(_latest_state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        # CS2 always expects a 200 even if we reject the body.
        self.send_response(200)
        self.end_headers()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return
        token = (payload.get("auth") or {}).get("token")
        if self.auth_token and token != self.auth_token:
            logging.warning("[cs2] rejected POST with bad auth token")
            return
        state = _parse_gsi(payload)
        with _state_lock:
            _latest_state.clear()
            _latest_state.update(state)
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                logging.exception("[cs2] on_state callback failed")


class GsiServer(threading.Thread):
    def __init__(self, host, port, on_state):
        super().__init__(daemon=True, name="CS2GsiServer")
        self.host = host
        self.port = port
        self.on_state = on_state
        self._httpd = None

    def run(self):
        from signal_companion.core.comutil import ensure_com_initialized
        ensure_com_initialized()
        handler = type("_BoundHandler", (_Handler,), {"on_state": staticmethod(self.on_state)})
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError:
            logging.exception(f"[cs2] could not bind {self.host}:{self.port} "
                              f"(port in use?) — receiver disabled")
            return
        logging.info(f"[cs2] GSI receiver listening on http://{self.host}:{self.port}")
        try:
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception:
            logging.exception("[cs2] server loop crashed")

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
        # Mark disconnected so the effect stops reacting after we quit.
        with _state_lock:
            _latest_state.clear()
            _latest_state.update({"connected": False, "ts": time.time()})


class Cs2GsiPlugin(Plugin):
    id = "cs2-gsi"
    name = "CS2 Integration"
    version = "1.0.0"
    description = "Receive CS2 Game State Integration and feed a SignalRGB effect."

    def __init__(self):
        self.ctx = None
        self.server = None
        self.https = None
        self._idle_thread = None
        self._stop = threading.Event()

    def default_config(self):
        return {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 3000,
            "https_port": 3443,       # HTTPS port the SignalRGB effect reads
            "auth_token": "signalcompanion",
            "cfg_dir": "",            # blank = auto-locate the CS2 cfg folder
        }

    def start(self, ctx):
        self.ctx = ctx
        cfg = ctx.config()
        if not cfg.get("enabled", True):
            ctx.log.info("disabled")
            return
        _Handler.auth_token = cfg.get("auth_token", "signalcompanion")
        self.server = GsiServer(cfg.get("host", "127.0.0.1"), int(cfg.get("port", 3000)),
                                on_state=self._on_state)
        self.server.start()
        # HTTPS bridge so the SignalRGB effect (Ultralight, public https origin)
        # can read /state — see tls_bridge for why http/localhost is blocked.
        self._start_https_bridge(cfg)
        # Watchdog: flip to "connected: false" if CS2 stops POSTing (game closed).
        self._idle_thread = threading.Thread(target=self._idle_watch, daemon=True,
                                              name="CS2IdleWatch")
        self._idle_thread.start()

    def _start_https_bridge(self, cfg):
        if not tls_bridge.available():
            self.ctx.log.warning("cryptography not available — SignalRGB HTTPS bridge disabled "
                                 "(effect can't read state)")
            return
        try:
            info = tls_bridge.ensure_certs(config_mod.CONFIG_DIR / "certs")
            patched = tls_bridge.patch_cacert(info["ca_pem"])
            if patched:
                self.ctx.log.info(f"trusted local CA in {len(patched)} Ultralight cacert.pem "
                                  "(restart SignalRGB once to load it)")
            else:
                self.ctx.log.warning("no Ultralight cacert.pem found to trust the CA "
                                     "(is SignalRGB installed?)")
            self.https = tls_bridge.HttpsStateServer(
                "127.0.0.1", int(cfg.get("https_port", 3443)),
                info["chain"], info["key"], _snapshot_state)
            self.https.start()
        except Exception:
            self.ctx.log.exception("HTTPS bridge setup failed")

    def _on_state(self, state):
        self.ctx.events.publish("cs2.state", state)
        hp = state.get("health")
        self.ctx.set_status({
            "label": f"CS2: {hp}HP" if hp is not None else "CS2: connected",
            "color": (90, 160, 90),
        })

    def _idle_watch(self):
        from signal_companion.core.comutil import ensure_com_initialized
        ensure_com_initialized()
        while not self._stop.wait(2.0):
            with _state_lock:
                connected = _latest_state.get("connected")
                stale = time.time() - _latest_state.get("ts", 0) > 10
                if connected and stale:
                    _latest_state["connected"] = False
            if connected and stale:
                self.ctx.events.publish("cs2.state", {"connected": False})
                self.ctx.set_status({"label": "CS2: idle", "color": (90, 90, 90)})

    def stop(self):
        self._stop.set()
        if self.server:
            self.server.stop()
        if self.https:
            self.https.stop()

    # ── settings tab ──
    def build_settings_tab(self, parent, cfg):
        vars = {}
        enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        ttk.Checkbutton(parent, text="Enable CS2 Game State receiver", variable=enabled).pack(anchor="w", pady=(0, 6))
        vars["enabled"] = enabled

        port_row = ttk.Frame(parent)
        port_row.pack(fill=tk.X, pady=4)
        ttk.Label(port_row, text="Listen port:").pack(side=tk.LEFT)
        port = tk.StringVar(value=str(cfg.get("port", 3000)))
        ttk.Entry(port_row, textvariable=port, width=8).pack(side=tk.LEFT, padx=6)
        vars["port"] = port

        tok_row = ttk.Frame(parent)
        tok_row.pack(fill=tk.X, pady=4)
        ttk.Label(tok_row, text="Auth token:").pack(side=tk.LEFT)
        token = tk.StringVar(value=cfg.get("auth_token", "signalcompanion"))
        ttk.Entry(tok_row, textvariable=token, width=24).pack(side=tk.LEFT, padx=6)
        vars["auth_token"] = token

        # ── CS2 GSI config (step 1) ──
        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="1) CS2 integration config:", font=("", 9, "bold")).pack(anchor="w")

        located = locate_cs2_cfg_dir() or "(not found — set manually)"
        ttk.Label(parent, text=f"CS2 cfg folder: {located}", foreground="#888",
                  wraplength=460, justify="left").pack(anchor="w", pady=(2, 4))

        def do_install_cfg():
            try:
                p = int(port.get())
            except ValueError:
                messagebox.showerror("Invalid", "Port must be a number")
                return
            try:
                dest = install_gsi_cfg(port=p, token=token.get().strip() or "signalcompanion",
                                       cfg_dir=cfg.get("cfg_dir") or None)
                messagebox.showinfo("Installed",
                                    f"Wrote gamestate_integration_signalcompanion.cfg to:\n{dest}\n\n"
                                    "Restart CS2 for it to take effect.")
            except Exception as e:
                messagebox.showerror("Install failed",
                                     f"{e}\n\nSet the CS2 cfg folder manually in config.json "
                                     "(plugins → cs2-gsi → cfg_dir).")

        def do_uninstall_cfg():
            try:
                dest = uninstall_gsi_cfg(cfg_dir=cfg.get("cfg_dir") or None)
            except Exception as e:
                messagebox.showerror("Uninstall failed", str(e))
                return
            if dest:
                messagebox.showinfo("Removed",
                                    f"Deleted:\n{dest}\n\nRestart CS2 for it to take effect.")
            else:
                messagebox.showinfo("Nothing to remove",
                                    "No SignalCompanion GSI config was found.")

        cfg_btns = ttk.Frame(parent)
        cfg_btns.pack(anchor="w", pady=(2, 6))
        ttk.Button(cfg_btns, text="Install CS2 GSI config…", command=do_install_cfg).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(cfg_btns, text="Uninstall", command=do_uninstall_cfg).pack(side=tk.LEFT)

        # ── SignalRGB effect / canvas (step 2) ──
        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="2) SignalRGB effect (the canvas):", font=("", 9, "bold")).pack(anchor="w")

        fx_dir = locate_effects_dir()
        ttk.Label(parent, text=f"Effects folder: {fx_dir}", foreground="#888",
                  wraplength=460, justify="left").pack(anchor="w", pady=(2, 4))

        def do_install_effect():
            try:
                dest = install_effect()
                messagebox.showinfo("Installed",
                                    f"Copied cs2_reactive.html to:\n{dest}\n\n"
                                    "In SignalRGB, apply the 'CS2 Reactive' effect to a layer and "
                                    f"set its Bridge port to {port.get()}.")
            except Exception as e:
                messagebox.showerror("Install failed", str(e))

        def do_uninstall_effect():
            try:
                dest = uninstall_effect()
            except Exception as e:
                messagebox.showerror("Uninstall failed", str(e))
                return
            if dest:
                messagebox.showinfo("Removed", f"Deleted:\n{dest}")
            else:
                messagebox.showinfo("Nothing to remove",
                                    "No CS2 Reactive effect was found in the Effects folder.")

        fx_btns = ttk.Frame(parent)
        fx_btns.pack(anchor="w", pady=(2, 6))
        ttk.Button(fx_btns, text="Install effect to SignalRGB", command=do_install_effect).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(fx_btns, text="Uninstall", command=do_uninstall_effect).pack(side=tk.LEFT)

        ttk.Label(parent, text=("The effect reacts to HP, low-HP pulse, flashbangs, bomb and team. "
                                "After installing, select it on a layer in SignalRGB."),
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w")
        return vars

    def save_settings(self, cfg, vars):
        cfg["enabled"] = bool(vars["enabled"].get())
        cfg["auth_token"] = vars["auth_token"].get().strip() or "signalcompanion"
        try:
            cfg["port"] = int(vars["port"].get())
        except ValueError:
            pass


PLUGIN = Cs2GsiPlugin()
