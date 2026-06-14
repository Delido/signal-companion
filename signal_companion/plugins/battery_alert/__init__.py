"""Battery Alert plugin (NEW).

Polls the headset battery via the Bragi read-property roundtrip
(core.devices.read_battery) and plays a sound when the level crosses below a
configurable threshold. Hysteresis prevents repeated alerts while the level
hovers around the threshold; a re-alert interval lets the alert repeat if the
battery keeps draining without being charged.

Publishes `headset.battery` on the EventBus (int percent) so other plugins /
the tray can show the level.
"""
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, ttk

from signal_companion.core.plugin import Plugin


def default_sound_path():
    """Path to the bundled low-battery chime (source tree or frozen bundle), or
    "" if it can't be located (caller then falls back to the system beep)."""
    here = Path(__file__).resolve().parent / "sounds" / "battery_low.wav"
    if here.is_file():
        return str(here)
    try:
        from importlib import resources
        with resources.as_file(
            resources.files("signal_companion.plugins.battery_alert")
            .joinpath("sounds", "battery_low.wav")
        ) as p:
            return str(p) if Path(p).is_file() else ""
    except Exception:
        return ""


class BatteryPoller(threading.Thread):
    def __init__(self, spec, get_config, ctx):
        super().__init__(daemon=True, name="BatteryPoller")
        self.spec = spec
        self.get_config = get_config
        self.ctx = ctx
        self._stop = threading.Event()
        self._below = False          # currently below threshold (hysteresis)
        self._last_alert = 0.0
        self._last_level = None

    def stop(self):
        self._stop.set()

    def run(self):
        if not self.spec:
            return
        while not self._stop.is_set():
            cfg = self.get_config()
            interval = max(15.0, float(cfg.get("poll_interval_seconds", 60.0)))
            if cfg.get("enabled", True):
                self._tick(cfg)
            self._stop.wait(interval)

    def _tick(self, cfg):
        level = self.ctx.devices.read_battery(self.spec)
        if level is None:
            return
        if level != self._last_level:
            self._last_level = level
            self.ctx.events.publish("headset.battery", level)
            self.ctx.set_status({
                "label": f"Battery: {level}%",
                "color": (220, 50, 50) if level <= cfg.get("threshold", 20) else (90, 160, 90),
            })
            self.ctx.log.info(f"battery {level}%")

        threshold = int(cfg.get("threshold", 20))
        # Hysteresis: clear the "below" latch only once we climb a few points
        # back above the threshold (e.g. plugged in to charge).
        if level > threshold + 5:
            self._below = False

        if level <= threshold:
            re_alert = max(0.0, float(cfg.get("re_alert_minutes", 30.0))) * 60.0
            now = time.monotonic()
            first_crossing = not self._below
            due_again = re_alert > 0 and (now - self._last_alert) >= re_alert
            if first_crossing or due_again:
                self._below = True
                self._last_alert = now
                self.ctx.log.info(f"battery low ({level}% ≤ {threshold}%) → alert")
                # Empty path → bundled battery chime; system beep only if that's
                # somehow missing too.
                self.ctx.play_sound(cfg.get("sound_path") or default_sound_path() or None)


class BatteryAlertPlugin(Plugin):
    id = "battery-alert"
    name = "Battery Alert"
    version = "1.0.0"
    description = "Play a sound when the headset battery drops below a threshold."

    def __init__(self):
        self.poller = None

    def default_config(self):
        return {
            "enabled": True,
            "device": "auto",
            "threshold": 20,                 # percent
            "poll_interval_seconds": 60.0,
            "re_alert_minutes": 30.0,        # 0 = alert once per crossing only
            "sound_path": "",                # empty → Windows default beep
        }

    def start(self, ctx):
        self.ctx = ctx
        spec = ctx.devices.resolve_headset(ctx.config().get("device", "auto"))
        if spec and spec.get("supports_battery"):
            ctx.log.info(f"battery source: {spec['label']}")
        else:
            ctx.log.info("battery: no battery-capable headset (inactive)")
            spec = None
        self.poller = BatteryPoller(spec, get_config=ctx.config, ctx=ctx)
        self.poller.start()

    def stop(self):
        if self.poller:
            self.poller.stop()

    def build_settings_tab(self, parent, cfg):
        from signal_companion.core.devices import headset_choices, choice_label_for_key
        vars = {}

        enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        ttk.Checkbutton(parent, text="Enable low-battery sound alert", variable=enabled).pack(anchor="w", pady=(0, 6))
        vars["enabled"] = enabled

        dev_row = ttk.Frame(parent)
        dev_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(dev_row, text="Headset:").pack(side=tk.LEFT)
        choices = headset_choices()
        dev_var = tk.StringVar(value=choice_label_for_key(choices, cfg.get("device", "auto")))
        ttk.Combobox(dev_row, textvariable=dev_var, values=[l for _, l in choices],
                     state="readonly", width=30).pack(side=tk.LEFT, padx=8)
        vars["device_var"] = dev_var
        vars["device_choices"] = choices

        thr_row = ttk.Frame(parent)
        thr_row.pack(fill=tk.X, pady=4)
        ttk.Label(thr_row, text="Alert threshold (%):").pack(side=tk.LEFT)
        threshold = tk.IntVar(value=int(cfg.get("threshold", 20)))
        ttk.Spinbox(thr_row, from_=1, to=99, textvariable=threshold, width=6).pack(side=tk.LEFT, padx=6)
        vars["threshold"] = threshold

        poll_row = ttk.Frame(parent)
        poll_row.pack(fill=tk.X, pady=4)
        ttk.Label(poll_row, text="Poll interval (seconds):").pack(side=tk.LEFT)
        interval = tk.StringVar(value=str(cfg.get("poll_interval_seconds", 60.0)))
        ttk.Entry(poll_row, textvariable=interval, width=8).pack(side=tk.LEFT, padx=6)
        vars["interval"] = interval

        re_row = ttk.Frame(parent)
        re_row.pack(fill=tk.X, pady=4)
        ttk.Label(re_row, text="Re-alert every (minutes, 0 = once):").pack(side=tk.LEFT)
        re_alert = tk.StringVar(value=str(cfg.get("re_alert_minutes", 30.0)))
        ttk.Entry(re_row, textvariable=re_alert, width=8).pack(side=tk.LEFT, padx=6)
        vars["re_alert"] = re_alert

        snd_row = ttk.Frame(parent)
        snd_row.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(snd_row, text="Sound (.wav, empty = built-in chime):").pack(side=tk.LEFT)
        sound_path = tk.StringVar(value=cfg.get("sound_path", ""))
        ttk.Entry(snd_row, textvariable=sound_path, width=24).pack(side=tk.LEFT, padx=6)

        def browse():
            p = filedialog.askopenfilename(title="Choose alert sound",
                                           filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")],
                                           parent=parent.winfo_toplevel())
            if p:
                sound_path.set(p)

        def test():
            from signal_companion.core import audio
            audio.play_sound(sound_path.get().strip() or default_sound_path() or None)

        ttk.Button(snd_row, text="Browse…", command=browse).pack(side=tk.LEFT)
        ttk.Button(snd_row, text="Test", command=test).pack(side=tk.LEFT, padx=(4, 0))
        vars["sound_path"] = sound_path

        ttk.Label(parent, text=("Battery is read directly from the headset over USB; works "
                                "alongside SignalRGB and iCUE without conflict."),
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", pady=(8, 0))
        return vars

    def save_settings(self, cfg, vars):
        from signal_companion.core.devices import choice_key_for_label
        cfg["enabled"] = bool(vars["enabled"].get())
        cfg["device"] = choice_key_for_label(vars["device_choices"], vars["device_var"].get())
        cfg["threshold"] = int(vars["threshold"].get())
        cfg["sound_path"] = vars["sound_path"].get().strip()
        try:
            cfg["poll_interval_seconds"] = max(15.0, float(vars["interval"].get()))
        except ValueError:
            pass
        try:
            cfg["re_alert_minutes"] = max(0.0, float(vars["re_alert"].get()))
        except ValueError:
            pass


PLUGIN = BatteryAlertPlugin()
