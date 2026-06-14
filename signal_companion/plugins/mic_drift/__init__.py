"""Mic Drift Logger plugin (migrated from feature_mic_drift.py).

Background diagnostic for the "mic suddenly twice as loud" bug. Snapshots the
Windows default-microphone state every N seconds and logs any change (volume
scalar/dB, mute, MMDevices registry FxProperties/Properties, default-device
id). Off by default; enable when actively debugging.
"""
import logging
import threading
import warnings
import winreg

from comtypes import CLSCTX_ALL, POINTER, cast
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import tkinter as tk
from tkinter import ttk

from signal_companion.core.comutil import ensure_com_initialized
from signal_companion.core.config import LOG_PATH
from signal_companion.core.plugin import Plugin

# Suppress pycaw's noisy "COMError getting property 68/69" warnings.
warnings.filterwarnings("ignore", category=UserWarning, module="pycaw.utils")

MMDEVICES_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"


def _read_subkey_values(full_key_path):
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, full_key_path) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = value.hex() if isinstance(value, bytes) else repr(value)
                i += 1
    except FileNotFoundError:
        pass
    except OSError as e:
        out["<error>"] = repr(e)
    return out


def _read_device_registry(device_id):
    if "}." not in device_id:
        return {}
    suffix = device_id.split("}.", 1)[1]
    base = f"{MMDEVICES_BASE}\\{suffix}"
    out = {}
    for sub in ("FxProperties", "Properties"):
        for k, v in _read_subkey_values(f"{base}\\{sub}").items():
            out[f"{sub}\\{k}"] = v
    return out


class MicDriftLogger(threading.Thread):
    def __init__(self, get_config):
        super().__init__(daemon=True, name="MicDriftLogger")
        self.get_config = get_config
        self._stop = threading.Event()
        self._last = None

    def stop(self):
        self._stop.set()

    def _snapshot(self):
        ensure_com_initialized()
        mic = AudioUtilities.GetMicrophone()
        dev_id = mic.GetId()
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        return {
            "id": dev_id,
            "scalar": round(vol.GetMasterVolumeLevelScalar(), 4),
            "db": round(vol.GetMasterVolumeLevel(), 2),
            "muted": bool(vol.GetMute()),
            "reg": _read_device_registry(dev_id),
        }

    def _diff_and_log(self, prev, cur):
        if prev["id"] != cur["id"]:
            logging.warning(f"[mic_drift] DEVICE CHANGED: {prev['id']} → {cur['id']}")
        if prev["scalar"] != cur["scalar"]:
            logging.warning(f"[mic_drift] SLIDER {prev['scalar']} → {cur['scalar']}")
        if prev["db"] != cur["db"]:
            logging.warning(f"[mic_drift] dB {prev['db']} → {cur['db']}")
        if prev["muted"] != cur["muted"]:
            logging.warning(f"[mic_drift] MUTE {prev['muted']} → {cur['muted']}")
        for k in sorted(set(prev["reg"]) | set(cur["reg"])):
            if prev["reg"].get(k) != cur["reg"].get(k):
                logging.warning(f"[mic_drift] REG {k}:")
                logging.warning(f"[mic_drift]     old: {prev['reg'].get(k)}")
                logging.warning(f"[mic_drift]     new: {cur['reg'].get(k)}")

    def run(self):
        logged_init = False
        while not self._stop.is_set():
            section = self.get_config()
            interval = max(1.0, float(section.get("poll_interval_seconds", 5.0)))
            if section.get("enabled", False):
                try:
                    cur = self._snapshot()
                    if self._last is None:
                        if not logged_init:
                            logging.info(f"[mic_drift] watching — scalar={cur['scalar']} "
                                         f"dB={cur['db']} muted={cur['muted']} regKeys={len(cur['reg'])}")
                            logged_init = True
                        self._last = cur
                    elif cur != self._last:
                        self._diff_and_log(self._last, cur)
                        self._last = cur
                except Exception:
                    logging.exception("[mic_drift] snapshot failed")
            else:
                self._last = None
                logged_init = False
            self._stop.wait(interval)


class MicDriftPlugin(Plugin):
    id = "mic-drift"
    name = "Mic Drift Logger"
    version = "2.0.0"
    description = "Diagnostic logging of unexpected mic volume / registry drift."

    def __init__(self):
        self.logger = None

    def default_config(self):
        return {"enabled": False, "poll_interval_seconds": 5.0}

    def start(self, ctx):
        self.logger = MicDriftLogger(get_config=ctx.config)
        self.logger.start()

    def stop(self):
        if self.logger:
            self.logger.stop()

    def build_settings_tab(self, parent, cfg):
        import os
        vars = {}
        enabled = tk.BooleanVar(value=cfg.get("enabled", False))
        ttk.Checkbutton(parent, text="Enable diagnostic logging of mic volume/registry drift",
                        variable=enabled).pack(anchor="w", pady=(0, 6))
        vars["enabled"] = enabled

        interval_row = ttk.Frame(parent)
        interval_row.pack(fill=tk.X, pady=(4, 8))
        ttk.Label(interval_row, text="Poll interval (seconds):").pack(side=tk.LEFT)
        interval = tk.StringVar(value=str(cfg.get("poll_interval_seconds", 5.0)))
        ttk.Entry(interval_row, textvariable=interval, width=8).pack(side=tk.LEFT, padx=6)
        vars["interval"] = interval

        ttk.Label(parent, text=("Watches the Windows default microphone for any unexpected "
                                "level / dB / mute / registry change and logs every transition "
                                "to watcher.log with a [mic_drift] prefix. Overhead: one HID "
                                "enumeration + one registry walk per interval."),
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", pady=(8, 0))
        ttk.Button(parent, text="Open log folder",
                   command=lambda: os.startfile(str(LOG_PATH.parent))).pack(anchor="w", pady=(12, 0))
        return vars

    def save_settings(self, cfg, vars):
        cfg["enabled"] = bool(vars["enabled"].get())
        try:
            cfg["poll_interval_seconds"] = max(1.0, float(vars["interval"].get()))
        except ValueError:
            pass


PLUGIN = MicDriftPlugin()
