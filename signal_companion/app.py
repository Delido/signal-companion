"""SignalCompanion — extensible tray companion for SignalRGB.

Fills the gaps SignalRGB's plugin sandbox leaves open (network, processes,
Windows audio, direct HID) via drop-in plugins discovered from the plugins/
package. The tray icon and menu are built from whatever plugins are loaded —
no per-feature wiring lives here.

Run modes:
    SignalCompanion.exe              tray + all enabled plugins
    SignalCompanion.exe --settings   settings dialog only (spawned by tray)
"""
import logging
import os
import subprocess
import sys
import threading

import pystray
from PIL import Image, ImageDraw

from signal_companion.core import config as config_mod
from signal_companion.core.manager import PluginManager


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
        self.manager = PluginManager(status_callback=self._on_status)

    # ── status / icon ──
    def _on_status(self, plugin_id, status):
        if self.icon:
            self.icon.icon = make_icon(self.manager.statuses)
            self.icon.title = self._title()

    def _title(self):
        parts = [st.get("label") for st in self.manager.statuses.values() if st.get("label")]
        return "SignalCompanion — " + (" | ".join(parts) if parts else "running")

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


def main():
    # Put the main thread in the multi-threaded COM apartment before anything
    # else. pycaw/comtypes objects get freed by the cyclic GC on arbitrary
    # threads; a uniformly-MTA process makes those cross-thread Releases safe
    # (otherwise the process dies with a native access violation in _ctypes).
    from signal_companion.core.comutil import ensure_com_initialized
    ensure_com_initialized()

    config_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(str(config_mod.LOG_PATH), encoding="utf-8")],
    )

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
