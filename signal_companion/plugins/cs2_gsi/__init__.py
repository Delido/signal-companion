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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tkinter as tk
from tkinter import messagebox, ttk

from signal_companion.core.plugin import Plugin
from .cfg_installer import install_gsi_cfg, locate_cs2_cfg_dir

# Shared latest-state, guarded by a lock. The HTTP handler writes it from the
# server thread; GET /state and the EventBus publish read it.
_state_lock = threading.Lock()
_latest_state = {"connected": False, "ts": 0}


def _parse_gsi(payload):
    """Map a raw CS2 GSI POST body to our flat, effect-friendly schema."""
    player = payload.get("player") or {}
    pstate = player.get("state") or {}
    rnd = payload.get("round") or {}
    mp = payload.get("map") or {}
    stats = player.get("match_stats") or {}

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
        "bomb": rnd.get("bomb"),                   # planted/defused/exploded
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
        self._idle_thread = None
        self._stop = threading.Event()

    def default_config(self):
        return {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 3000,
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
        # Watchdog: flip to "connected: false" if CS2 stops POSTing (game closed).
        self._idle_thread = threading.Thread(target=self._idle_watch, daemon=True,
                                              name="CS2IdleWatch")
        self._idle_thread.start()

    def _on_state(self, state):
        self.ctx.events.publish("cs2.state", state)
        hp = state.get("health")
        self.ctx.set_status({
            "label": f"CS2: {hp}HP" if hp is not None else "CS2: connected",
            "color": (90, 160, 90),
        })

    def _idle_watch(self):
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

        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="CS2 integration config:", font=("", 9, "bold")).pack(anchor="w")

        located = locate_cs2_cfg_dir() or "(not found — set manually)"
        ttk.Label(parent, text=f"CS2 cfg folder: {located}", foreground="#888",
                  wraplength=460, justify="left").pack(anchor="w", pady=(2, 4))

        def do_install():
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
        ttk.Button(parent, text="Install CS2 GSI config…", command=do_install).pack(anchor="w", pady=(2, 6))

        ttk.Label(parent, text=("Then load the bundled SignalRGB effect (see the cs2_gsi/effect "
                                "folder) so the lighting reacts to HP, bomb, flashbangs and team."),
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
