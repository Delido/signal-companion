"""Audio Output Switcher plugin.

Knows all of the machine's playback devices and exposes a tiny local HTTP
endpoint so a SignalRGB macro (or anything that can open a URL / run curl) can
rotate the Windows default output device — e.g. flip headset ↔ speakers with a
single key.

Endpoints (default http://127.0.0.1:3010):
    GET /next        rotate to the next device in the configured rotation
    GET /prev        rotate to the previous one
    GET /set?name=X  switch to the active device whose name contains X
    GET /set?id=...  switch to a specific endpoint id
    GET /set?i=N     switch to rotation member N (0-based)
    GET /current     report the current default device
    GET /devices     list active playback devices (and rotation membership)

Which devices take part in the rotation is configured in the Settings tab. The
actual device-switching lives in winaudio.py (undocumented IPolicyConfig).
"""
import json
import logging
import os
import queue
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tkinter as tk
from tkinter import messagebox, ttk

from signal_companion.core.comutil import ensure_com_initialized
from signal_companion.core.plugin import Plugin
from . import winaudio


# ── rotation logic (pure; shared by the live plugin and the settings "Test") ──
def _members(configured, active):
    """The rotation members that are currently active, in configured order.
    Falls back to *all* active devices when nothing is configured/connected."""
    active_ids = {d["id"] for d in active}
    members = [d for d in configured if d in active_ids]
    return members or [d["id"] for d in active]


def rotate(direction, configured):
    """Switch the default device to the next/prev rotation member.
    Returns (device_dict, error_str|None)."""
    active = winaudio.list_render_devices()
    if not active:
        return None, "no active output devices"
    members = _members(configured, active)
    by_id = {d["id"]: d for d in active}
    cur = next((d["id"] for d in active if d["default"]), None)
    if cur in members:
        nxt = members[(members.index(cur) + direction) % len(members)]
    else:
        nxt = members[0]
    winaudio.set_default(nxt)
    return by_id.get(nxt, {"id": nxt, "name": nxt}), None


def set_target(params, configured):
    """Switch to a device chosen by ?id= / ?name= / ?i=. Returns (dev, err)."""
    active = winaudio.list_render_devices()
    by_id = {d["id"]: d for d in active}
    target = None
    if "id" in params:
        tid = params["id"][0]
        target = tid if tid in by_id else None
    elif "name" in params:
        sub = params["name"][0].lower()
        target = next((d["id"] for d in active if sub in d["name"].lower()), None)
    elif "i" in params:
        members = _members(configured, active)
        try:
            target = members[int(params["i"][0])]
        except (ValueError, IndexError):
            target = None
    if not target:
        return None, "device not found"
    winaudio.set_default(target)
    return by_id.get(target, {"id": target, "name": target}), None


def _short_name(name):
    return name.split(" (")[0] if " (" in name else name


def create_switch_shortcut(action="next"):
    """Create a no-window 'Audio Switch' shortcut on the Desktop that runs this
    same trusted exe with --audio-switch. Returns the .lnk path."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Shortcuts target the installed SignalCompanion.exe — "
                           "available in the installed build only.")
    target = sys.executable  # SignalCompanion.exe
    args = "--audio-switch" + ("" if action == "next" else f" {action}")
    name = "Audio Switch" + ("" if action == "next" else f" ({action})")
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    lnk = os.path.join(desktop, f"{name}.lnk")
    import comtypes.client
    shell = comtypes.client.CreateObject("WScript.Shell")
    sc = shell.CreateShortcut(lnk)
    sc.TargetPath = target
    sc.Arguments = args
    sc.WorkingDirectory = os.path.dirname(target)
    sc.IconLocation = target
    sc.Description = "Rotate the default audio output device"
    sc.Save()
    return lnk


# ── HTTP endpoint ──
class _Handler(BaseHTTPRequestHandler):
    controller = None  # set on a bound subclass per server

    def log_message(self, *args):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        ensure_com_initialized()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = urllib.parse.parse_qs(parsed.query)
        c = self.controller
        try:
            if path in ("/next", "/toggle"):
                dev, err = c.rotate(1)
            elif path == "/prev":
                dev, err = c.rotate(-1)
            elif path == "/set":
                dev, err = c.set_target(params)
            elif path == "/current":
                return self._send(200, {"ok": True, "current": c.current()})
            elif path == "/devices":
                return self._send(200, {"ok": True, "devices": c.devices()})
            elif path in ("/", "/help"):
                return self._send(200, {
                    "ok": True,
                    "endpoints": ["/next", "/prev", "/set?name=", "/set?id=",
                                  "/set?i=", "/current", "/devices"],
                })
            else:
                return self._send(404, {"ok": False, "error": "unknown endpoint"})
        except Exception as e:
            logging.exception("[audio] request failed")
            return self._send(500, {"ok": False, "error": str(e)})
        if err:
            return self._send(409, {"ok": False, "error": err})
        self._send(200, {"ok": True, "current": dev})


class _AudioWorker(threading.Thread):
    """Single, long-lived MTA thread that performs ALL audio COM work.

    The HTTP server handles each request on its own (ephemeral) thread; if those
    threads created/released comtypes/pycaw COM objects concurrently, the churn
    corrupted COM object lifetimes and crashed the process natively during GC
    (comtypes Release → access violation, seen in fault.log). Funnelling every
    COM call through one persistent thread removes that concurrency entirely, and
    a gc.collect() after each job finalizes any comtypes cycles here, on this
    COM-initialized thread, rather than later on some unrelated thread."""

    def __init__(self):
        super().__init__(daemon=True, name="AudioWorker")
        self._q = queue.Queue()
        self._stop = threading.Event()

    def submit(self, fn, timeout=10.0):
        """Run fn() on the audio thread and return its result (blocking)."""
        if self._stop.is_set() or not self.is_alive():
            return fn()  # fallback: run inline (e.g. during shutdown)
        box = {}
        done = threading.Event()
        self._q.put((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError("audio worker timed out")
        if "exc" in box:
            raise box["exc"]
        return box.get("value")

    def run(self):
        ensure_com_initialized()
        while not self._stop.is_set():
            try:
                fn, box, done = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                box["value"] = fn()
            except Exception as e:  # noqa: BLE001 — propagated to the caller
                box["exc"] = e
            finally:
                done.set()

    def stop(self):
        self._stop.set()


class _Controller:
    """Binds the pure rotation helpers to the plugin's live config + tray, and
    runs every COM operation on the single audio worker thread."""

    def __init__(self, get_config, on_change, worker):
        self.get_config = get_config
        self.on_change = on_change
        self.worker = worker

    def _configured(self):
        return list(self.get_config().get("devices") or [])

    def rotate(self, direction):
        configured = self._configured()
        dev, err = self.worker.submit(lambda: rotate(direction, configured))
        if dev and not err:
            self.on_change(dev)
        return dev, err

    def set_target(self, params):
        configured = self._configured()
        dev, err = self.worker.submit(lambda: set_target(params, configured))
        if dev and not err:
            self.on_change(dev)
        return dev, err

    def current(self):
        def _work():
            active = winaudio.list_render_devices()
            return next((d for d in active if d["default"]), None)
        return self.worker.submit(_work)

    def devices(self):
        configured = self._configured()

        def _work():
            active = winaudio.list_render_devices()
            for d in active:
                d["in_rotation"] = d["id"] in configured
            return active
        return self.worker.submit(_work)


class _Server(threading.Thread):
    def __init__(self, host, port, controller):
        super().__init__(daemon=True, name="AudioRouterServer")
        self.host = host
        self.port = port
        self.controller = controller
        self._httpd = None

    def run(self):
        ensure_com_initialized()
        handler = type("_BoundHandler", (_Handler,), {"controller": self.controller})
        try:
            self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError:
            logging.exception(f"[audio] could not bind {self.host}:{self.port} "
                              "(port in use?) — switcher disabled")
            return
        logging.info(f"[audio] output switcher listening on http://{self.host}:{self.port}")
        try:
            self._httpd.serve_forever(poll_interval=0.5)
        except Exception:
            logging.exception("[audio] server loop crashed")

    def stop(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass


class AudioRouterPlugin(Plugin):
    id = "audio-router"
    name = "Audio Output Switcher"
    version = "1.0.0"
    description = "Rotate the Windows default output device via a local URL (for SignalRGB macros)."

    def __init__(self):
        self.ctx = None
        self.server = None
        self.controller = None
        self.worker = None

    def default_config(self):
        return {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 3010,
            "devices": [],   # ordered endpoint ids that take part in the rotation
            "toast": True,    # show a tray toast on every switch
        }

    def start(self, ctx):
        self.ctx = ctx
        cfg = ctx.config()
        if not cfg.get("enabled", True):
            ctx.log.info("disabled")
            return
        self.worker = _AudioWorker()
        self.worker.start()
        self.controller = _Controller(ctx.config, self._on_change, self.worker)
        self.server = _Server(cfg.get("host", "127.0.0.1"), int(cfg.get("port", 3010)),
                              self.controller)
        self.server.start()
        # Show the current device in the tray on startup.
        try:
            cur = self.controller.current()
            if cur:
                self._on_change(cur, switched=False)
        except Exception:
            ctx.log.exception("initial device read failed")

    def stop(self):
        if self.server:
            self.server.stop()
        if self.worker:
            self.worker.stop()

    def _on_change(self, dev, switched=True):
        if not self.ctx:
            return
        full = dev.get("name", "?")
        self.ctx.set_status({"label": f"Audio: {_short_name(full)}", "color": (90, 130, 170)})
        if switched:
            self.ctx.log.info(f"output → {full}")
            self.ctx.events.publish("audio.default", dev)
            if self.ctx.config().get("toast", True):
                self.ctx.notify("Audio output", full)

    # ── settings tab ──
    def build_settings_tab(self, parent, cfg):
        vars = {}
        enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        ttk.Checkbutton(parent, text="Enable Audio Output Switcher", variable=enabled).pack(anchor="w", pady=(0, 6))
        vars["enabled"] = enabled

        port_row = ttk.Frame(parent)
        port_row.pack(fill=tk.X, pady=4)
        ttk.Label(port_row, text="Endpoint port:").pack(side=tk.LEFT)
        port = tk.StringVar(value=str(cfg.get("port", 3010)))
        ttk.Entry(port_row, textvariable=port, width=8).pack(side=tk.LEFT, padx=6)
        vars["port"] = port

        ttk.Label(parent, text=f"Macro URL (rotate):  http://127.0.0.1:{cfg.get('port', 3010)}/next",
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", pady=(2, 2))
        ttk.Label(parent, text="Bind that URL to a key in SignalRGB (or use curl) to flip the "
                               "default output device.", foreground="#888",
                  justify="left", wraplength=460).pack(anchor="w", pady=(0, 4))

        toast = tk.BooleanVar(value=cfg.get("toast", True))
        ttk.Checkbutton(parent, text="Show a notification (toast) on each switch",
                        variable=toast).pack(anchor="w", pady=(2, 0))
        vars["toast"] = toast

        # ── no-window switch via this same exe ──
        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="No-window switch (for launchers that run a program):",
                  font=("", 9, "bold")).pack(anchor="w")
        exe = sys.executable if getattr(sys, "frozen", False) else "SignalCompanion.exe"
        ttk.Label(parent, text="Bind THIS exe with the argument --audio-switch (it opens no window "
                               "and just rotates the output):",
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", pady=(0, 2))
        ttk.Label(parent, text=f"Application:  {exe}\nArguments:    --audio-switch",
                  foreground="#aaa", font=("Consolas", 9), justify="left").pack(anchor="w", pady=(0, 4))
        ttk.Label(parent, text="(Use the full path above as the application, and put --audio-switch "
                               "in the Arguments field — same as any other program.)",
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", pady=(0, 4))

        def do_make_shortcut():
            try:
                lnk = create_switch_shortcut("next")
                messagebox.showinfo("Shortcut created",
                                    f"Created:\n{lnk}\n\nYou can drag it anywhere, or point your "
                                    "launcher at it. It runs with no window.")
            except Exception as e:
                messagebox.showerror("Shortcut failed", str(e))

        ttk.Button(parent, text="Create 'Audio Switch' shortcut on Desktop",
                   command=do_make_shortcut).pack(anchor="w", pady=(0, 2))

        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="Output devices in the rotation:", font=("", 9, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Tick the devices /next should cycle through (in this order). "
                               "● marks the current Windows default.",
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", pady=(0, 4))

        try:
            active = winaudio.list_render_devices()
        except Exception:
            active = []
            ttk.Label(parent, text="(could not read audio devices)", foreground="#c66").pack(anchor="w")

        configured = list(cfg.get("devices") or [])
        active_by_id = {d["id"]: d for d in active}
        # Configured devices first (preserve order, keep disconnected ones visible),
        # then any other currently-active devices.
        rows, seen = [], set()
        for did in configured:
            rows.append((did, active_by_id.get(did)))
            seen.add(did)
        for d in active:
            if d["id"] not in seen:
                rows.append((d["id"], d))

        dev_vars = {}
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.X, anchor="w")
        for did, d in rows:
            present = d is not None
            name = (d or {}).get("name") or did
            label = name
            if (d or {}).get("default"):
                label += "  ●"
            if not present:
                label += "  (not connected)"
            v = tk.BooleanVar(value=did in configured)
            ttk.Checkbutton(list_frame, text=label, variable=v).pack(anchor="w")
            dev_vars[did] = v
        vars["dev_vars"] = dev_vars
        vars["dev_order"] = [did for did, _ in rows]

        def do_test():
            chosen = [did for did in vars["dev_order"] if dev_vars[did].get()]
            try:
                dev, err = rotate(1, chosen)
            except Exception as e:
                messagebox.showerror("Audio Output Switcher", str(e))
                return
            if err:
                messagebox.showwarning("Audio Output Switcher", err)
            else:
                messagebox.showinfo("Audio Output Switcher", f"Switched to:\n{dev['name']}")

        ttk.Label(parent, text="(Reopen Settings to refresh the device list.)",
                  foreground="#888").pack(anchor="w", pady=(6, 2))
        ttk.Button(parent, text="Test: switch to next now", command=do_test).pack(anchor="w")
        return vars

    def save_settings(self, cfg, vars):
        cfg["enabled"] = bool(vars["enabled"].get())
        cfg["toast"] = bool(vars["toast"].get())
        try:
            cfg["port"] = int(vars["port"].get())
        except ValueError:
            pass
        order = vars.get("dev_order", [])
        dev_vars = vars.get("dev_vars", {})
        cfg["devices"] = [did for did in order if dev_vars[did].get()]


PLUGIN = AudioRouterPlugin()
