"""SignalCompanion — extensible tray companion for SignalRGB.

Fills the gaps SignalRGB's plugin sandbox leaves open (network, processes,
Windows audio, direct HID) via drop-in plugins discovered from the plugins/
package. The tray icon and menu are built from whatever plugins are loaded —
no per-feature wiring lives here.

Run modes:
    SignalCompanion.exe              tray + all enabled plugins
    SignalCompanion.exe --settings   settings dialog only (spawned by tray)
"""
import faulthandler
import logging
import os
import subprocess
import sys
import threading

import pystray
from PIL import Image, ImageDraw

from signal_companion.core import config as config_mod
from signal_companion.core.manager import PluginManager

# Kept open for the process lifetime so faulthandler can write native crash
# stacks to it (see main()).
_FAULT_FILE = None


def make_icon(statuses):
    """64x64 RGBA tray icon: a vertical stack of indicator dots, one per
    plugin that reported a status (color from the plugin). Falls back to a
    single neutral dot when nothing has reported yet."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(34, 34, 38), outline=(20, 20, 20), width=2)

    items = list(statuses.values()) or [{"color": (90, 90, 90)}]
    items = items[:4]                       # cap so dots stay legible
    n = len(items)
    gap = 52 // max(n, 1)
    size = min(18, gap - 4)
    y = 8
    for st in items:
        color = tuple(st.get("color", (90, 90, 90)))
        cx = 32
        draw.ellipse([cx - size // 2, y, cx + size // 2, y + size], fill=color)
        y += gap
    return img


class TrayApp:
    def __init__(self):
        self.icon = None
        # pystray's Win32 icon is NOT thread-safe: concurrent icon/title/notify
        # calls (e.g. plugins firing from their own worker threads) can race in
        # the HICON create/DestroyIcon path and crash the process natively. All
        # tray mutations go through this lock so they're serialized.
        self._tray_lock = threading.Lock()
        self.manager = PluginManager(status_callback=self._on_status,
                                     notify_callback=self._notify)

    # ── status / icon ──
    def _on_status(self, plugin_id, status):
        if not self.icon:
            return
        with self._tray_lock:
            try:
                self.icon.icon = make_icon(self.manager.statuses)
                self.icon.title = self._title()
            except Exception:
                logging.exception("[app] tray icon update failed")

    def _title(self):
        parts = [st.get("label") for st in self.manager.statuses.values() if st.get("label")]
        return "SignalCompanion — " + (" | ".join(parts) if parts else "running")

    def _notify(self, title, message):
        """Show a tray notification (Windows toast/balloon) on behalf of a plugin."""
        if not self.icon:
            return
        with self._tray_lock:
            try:
                self.icon.notify(message, title)
            except Exception:
                logging.exception("[app] tray notify failed")

    # ── menu actions ──
    def _spawn_settings(self):
        if getattr(sys, "frozen", False):
            proc = subprocess.Popen([sys.executable, "--settings"])
        else:
            proc = subprocess.Popen([sys.executable, "-m", "signal_companion.app", "--settings"])
        # Reload config once the settings window closes, so live changes apply.
        threading.Thread(target=self._reload_after, args=(proc,), daemon=True).start()

    def _reload_after(self, proc):
        try:
            proc.wait()
        except Exception:
            return
        self.manager.reload_config()
        logging.info("[app] config reloaded after settings dialog closed")

    def _open_log_folder(self):
        os.startfile(str(config_mod.LOG_PATH.parent))

    def _quit(self):
        logging.info("Quit requested")
        self.manager.stop_all()
        if self.icon:
            self.icon.stop()

    def _build_menu(self):
        items = [pystray.MenuItem("Settings…", lambda: self._spawn_settings())]
        # Let plugins contribute menu items.
        for plugin in self.manager.plugins:
            try:
                for label, callback in plugin.tray_menu_items():
                    items.append(pystray.MenuItem(label, (lambda cb: lambda: cb())(callback)))
            except Exception:
                logging.exception(f"[app] tray_menu_items failed for {plugin.id}")
        items += [
            pystray.MenuItem("Open log folder", lambda: self._open_log_folder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self._quit()),
        ]
        return pystray.Menu(*items)

    def run(self):
        self.manager.discover()
        self.manager.start_all()
        self.icon = pystray.Icon(
            "SignalCompanion", make_icon(self.manager.statuses),
            self._title(), self._build_menu(),
        )
        self.icon.run()
        # If we get here, the tray message loop ended on its own (not a native
        # crash — those leave no log; see fault.log). Distinguishes "quit"/clean
        # loop-exit from a hard crash when diagnosing "the tray disappeared".
        logging.warning("[app] tray icon loop returned — message loop ended "
                        "(clean exit, not a native crash)")


def _audio_switch(action):
    """No-window trigger: ask the running tray to rotate the audio output, then
    exit. Reuses this same trusted onedir exe (`SignalCompanion.exe
    --audio-switch [next|prev|set?name=…]`) so there's no separate self-extracting
    helper for Defender/SmartScreen to choke on. Stays silent if the tray's
    endpoint isn't up — there's nothing to switch."""
    import json
    import urllib.request
    try:
        with open(config_mod.CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
        port = int(cfg.get("plugins", {}).get("audio-router", {}).get("port", 3010))
    except Exception:
        port = 3010
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/{action.lstrip('/')}", timeout=4).read()
    except Exception:
        pass


def main():
    # Fast, side-effect-free path for the audio-switch trigger — before COM init,
    # logging or the tray, so it opens no window and returns instantly.
    if len(sys.argv) > 1 and sys.argv[1] == "--audio-switch":
        _audio_switch(sys.argv[2] if len(sys.argv) > 2 else "next")
        return

    # Put the main thread in the multi-threaded COM apartment before anything
    # else. pycaw/comtypes objects get freed by the cyclic GC on arbitrary
    # threads; a uniformly-MTA process makes those cross-thread Releases safe
    # (otherwise the process dies with a native access violation in _ctypes).
    from signal_companion.core.comutil import ensure_com_initialized
    ensure_com_initialized()

    config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Capture *native* crashes (access violations etc. that leave no Python
    # traceback) to fault.log, with every thread's stack. The frozen app is
    # windowed (no console/stderr), so faulthandler must write to a real file;
    # keep the handle open for the whole process lifetime.
    global _FAULT_FILE
    try:
        _FAULT_FILE = open(str(config_mod.CONFIG_DIR / "fault.log"), "w", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE, all_threads=True)
    except Exception:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(str(config_mod.LOG_PATH), encoding="utf-8")],
    )

    # Log any unhandled exception on any thread, so a Python-level crash that
    # would otherwise vanish (windowed app, no console) lands in watcher.log.
    def _log_unhandled(exc_type, exc, tb):
        logging.error("UNHANDLED EXCEPTION", exc_info=(exc_type, exc, tb))
    sys.excepthook = _log_unhandled
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda a: logging.error(
            "UNHANDLED THREAD EXCEPTION in %s", a.thread,
            exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        from signal_companion.ui import settings_app
        settings_app.run()
        return

    logging.info("=== SignalCompanion starting ===")
    try:
        TrayApp().run()
    except Exception:
        logging.exception("Tray app crashed")
        raise


if __name__ == "__main__":
    main()
