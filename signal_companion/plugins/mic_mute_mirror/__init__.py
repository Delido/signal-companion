"""Mic Mute Mirror plugin (migrated from feature_mic_mute.py).

Bidirectional sync between a supported headset's hardware mute button and the
Windows default microphone:
  - hardware_to_windows: headset button → IAudioEndpointVolume.SetMute
  - windows_to_hardware: Windows mute → headset SET-property pair (LED + audio)

Headset-specific constants come from core.devices.SUPPORTED_HEADSETS.
"""
import logging
import threading

import pywinusb.hid as hid
from comtypes import CLSCTX_ALL, POINTER, cast
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import tkinter as tk
from tkinter import ttk

from signal_companion.core.comutil import ensure_com_initialized
from signal_companion.core.plugin import Plugin


# ── Windows-side controller ──
class MicController:
    """Cached IAudioEndpointVolume on the Windows default microphone."""

    def __init__(self):
        self._volume = None

    def _open(self):
        ensure_com_initialized()
        try:
            mic = AudioUtilities.GetMicrophone()
            interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self._volume = cast(interface, POINTER(IAudioEndpointVolume))
            return True
        except Exception:
            logging.exception("[mic_mute] failed to open default microphone")
            self._volume = None
            return False

    def set_mute(self, muted: bool) -> bool:
        ensure_com_initialized()
        if self._volume is None and not self._open():
            return False
        try:
            self._volume.SetMute(1 if muted else 0, None)
            return True
        except Exception:
            logging.exception("[mic_mute] SetMute failed; will reopen next time")
            self._volume = None
            return False

    def get_mute(self):
        ensure_com_initialized()
        if self._volume is None and not self._open():
            return None
        try:
            return bool(self._volume.GetMute())
        except Exception:
            self._volume = None
            return None


# ── Headset event listener ──
class HeadsetMicWatcher(threading.Thread):
    def __init__(self, device_spec, mic_controller, get_config, on_state_change=None):
        super().__init__(daemon=True, name="HeadsetMicWatcher")
        self.spec = device_spec
        self.mic = mic_controller
        self.get_config = get_config
        self.on_state_change = on_state_change
        self._stop = threading.Event()
        self._device = None
        self.last_state = None

    def stop(self):
        self._stop.set()
        self._close()

    def _open(self):
        self._close()
        if not self.spec:
            return False
        for d in hid.HidDeviceFilter(vendor_id=self.spec["vid"], product_id=self.spec["pid"]).get_devices():
            try:
                d.open()
                caps = d.hid_caps
                if (caps and caps.usage_page == self.spec["event_usage_page"]
                        and caps.usage == self.spec["event_usage"]):
                    d.set_raw_data_handler(self._on_report)
                    self._device = d
                    logging.info(f"[mic_mute] Listening on {self.spec['label']} event channel")
                    return True
                d.close()
            except Exception:
                try:
                    d.close()
                except Exception:
                    pass
        return False

    def _close(self):
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def _on_report(self, data):
        # Event format `03 01 01 <mic_register> 00 <V>`; pywinusb does NOT
        # prepend a report-ID byte on this collection — data[0] is wire byte 0.
        if len(data) < 6:
            return
        if data[0] != 0x03 or data[1] != 0x01 or data[2] != 0x01:
            return
        if data[3] != self.spec["mic_register"]:
            return
        muted = bool(data[5])
        if muted == self.last_state:
            return
        self.last_state = muted

        cfg = self.get_config()
        if not cfg.get("enabled", True) or not cfg.get("hardware_to_windows", True):
            logging.info(f"[mic_mute] hardware → {'MUTED' if muted else 'UNMUTED'} (HW→Win disabled)")
            self._notify(muted)
            return
        if self.mic.set_mute(muted):
            logging.info(f"[mic_mute] hardware → {'MUTED' if muted else 'UNMUTED'} → Windows mic synced")
            self._notify(muted)
        else:
            logging.warning("[mic_mute] mic toggle failed")

    def _notify(self, muted):
        if self.on_state_change:
            try:
                self.on_state_change(muted)
            except Exception:
                logging.exception("[mic_mute] state callback failed")

    def run(self):
        if not self.spec:
            return
        while not self._stop.is_set():
            if self._device is None:
                if not self._open():
                    self._stop.wait(5.0)
                    continue
            self._stop.wait(2.0)


# ── Headset command writer ──
class HeadsetMuteWriter:
    """Pushes mute state to the headset command channel as a paired SET:
    led_echo_register then mic_register, both with the same value byte.

    This collection's output report is *numbered* (report_id=0x02); pywinusb
    expects payload[0] to be the report ID AND that byte IS transmitted, so
    the leading 0x02 doubles as report ID and conn-byte."""

    def __init__(self, device_spec):
        self.spec = device_spec
        self._device = None

    def _open(self):
        self._close()
        if not self.spec:
            return False
        for d in hid.HidDeviceFilter(vendor_id=self.spec["vid"], product_id=self.spec["pid"]).get_devices():
            try:
                d.open()
                caps = d.hid_caps
                if (caps and caps.usage_page == self.spec["cmd_usage_page"]
                        and caps.usage == self.spec["cmd_usage"]):
                    self._device = d
                    logging.info(f"[mic_mute/writer] Opened {self.spec['label']} command channel")
                    return True
                d.close()
            except Exception:
                try:
                    d.close()
                except Exception:
                    pass
        return False

    def _close(self):
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    close = _close

    def _send_set(self, register, value):
        reports = self._device.find_output_reports()
        if not reports:
            return False
        report = reports[0]
        out_len = self._device.hid_caps.output_report_byte_length or 65
        payload = bytearray(out_len)
        wire = [0x02, self.spec["wireless_mode"], 0x01, register, 0x00, value]
        for i, b in enumerate(wire):
            if i >= out_len:
                break
            payload[i] = b
        report.set_raw_data(list(payload))
        return bool(report.send())

    def set_mute(self, muted: bool) -> bool:
        if not self.spec:
            return False
        if self._device is None and not self._open():
            return False
        v = 0x01 if muted else 0x00
        try:
            ok1 = self._send_set(self.spec["led_echo_register"], v)
            ok2 = self._send_set(self.spec["mic_register"], v)
            return ok1 and ok2
        except Exception:
            logging.exception("[mic_mute/writer] send failed; will reopen next time")
            self._close()
            return False


# ── Windows-side watcher ──
class WindowsMicMuteWatcher(threading.Thread):
    def __init__(self, mic_controller, headset_writer, get_config):
        super().__init__(daemon=True, name="WindowsMicMuteWatcher")
        self.mic = mic_controller
        self.headset = headset_writer
        self.get_config = get_config
        self._stop = threading.Event()
        self.last_state = None
        self.poll_interval = 0.5

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                cur = self.mic.get_mute()
                if cur is not None:
                    if self.last_state is None:
                        self.last_state = cur
                    elif cur != self.last_state:
                        self.last_state = cur
                        cfg = self.get_config()
                        if cfg.get("enabled", True) and cfg.get("windows_to_hardware", True):
                            logging.info(f"[mic_mute/win] Windows mic → {'MUTED' if cur else 'UNMUTED'} → syncing headset")
                            self.headset.set_mute(cur)
                        else:
                            logging.info(f"[mic_mute/win] Windows mic → {'MUTED' if cur else 'UNMUTED'} (Win→HW disabled)")
            except Exception:
                logging.exception("[mic_mute/win] poll failed")
            self._stop.wait(self.poll_interval)


class MicMuteMirrorPlugin(Plugin):
    id = "mic-mute-mirror"
    name = "Mic Mute Mirror"
    version = "2.0.0"
    description = "Bidirectional sync between headset mute button and Windows mic."

    def __init__(self):
        self.ctx = None
        self.mic = None
        self.writer = None
        self.hs_watcher = None
        self.win_watcher = None

    def default_config(self):
        return {
            "enabled": True,
            "device": "auto",
            "hardware_to_windows": True,
            "windows_to_hardware": True,
        }

    def start(self, ctx):
        self.ctx = ctx
        spec = ctx.devices.resolve_headset(ctx.config().get("device", "auto"))
        if spec:
            ctx.log.info(f"headset: {spec['label']}")
        else:
            ctx.log.info("headset: none (Mic Mute Mirror inactive)")
        self.mic = MicController()
        self.writer = HeadsetMuteWriter(spec)
        self.hs_watcher = HeadsetMicWatcher(spec, self.mic, get_config=ctx.config,
                                            on_state_change=self._on_change)
        self.win_watcher = WindowsMicMuteWatcher(self.mic, self.writer, get_config=ctx.config)
        self.hs_watcher.start()
        self.win_watcher.start()

    def stop(self):
        if self.hs_watcher:
            self.hs_watcher.stop()
        if self.win_watcher:
            self.win_watcher.stop()
        if self.writer:
            self.writer.close()

    def _on_change(self, muted):
        if self.ctx:
            self.ctx.set_status({
                "label": f"Mic: {'MUTED' if muted else 'live'}",
                "color": (220, 50, 50) if muted else (90, 90, 90),
            })
            self.ctx.events.publish("mic.muted", muted)

    # ── settings tab ──
    def build_settings_tab(self, parent, cfg):
        from signal_companion.core.devices import headset_choices, choice_label_for_key
        vars = {}

        enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        ttk.Checkbutton(parent, text="Enable Mic Mute Mirror", variable=enabled).pack(anchor="w", pady=(0, 6))
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

        ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=8)
        ttk.Label(parent, text="Sync directions:", font=("", 9, "bold")).pack(anchor="w")

        hw_to_win = tk.BooleanVar(value=cfg.get("hardware_to_windows", True))
        ttk.Checkbutton(parent, text="Headset mute button → Windows default mic mute",
                        variable=hw_to_win).pack(anchor="w", padx=12, pady=2)
        vars["hw_to_win"] = hw_to_win

        win_to_hw = tk.BooleanVar(value=cfg.get("windows_to_hardware", True))
        ttk.Checkbutton(parent, text="Windows mic mute → Headset hardware (LED + USB-audio)",
                        variable=win_to_hw).pack(anchor="w", padx=12, pady=2)
        vars["win_to_hw"] = win_to_hw

        ttk.Label(parent, text=("Why both? Some apps (Discord) bypass the Windows-side mute via "
                                "raw capture. The Windows→Headset direction cuts the mic at the "
                                "device level, which Discord cannot bypass."),
                  foreground="#888", justify="left", wraplength=460).pack(anchor="w", padx=12, pady=(4, 0))
        return vars

    def save_settings(self, cfg, vars):
        from signal_companion.core.devices import choice_key_for_label
        cfg["enabled"] = bool(vars["enabled"].get())
        cfg["device"] = choice_key_for_label(vars["device_choices"], vars["device_var"].get())
        cfg["hardware_to_windows"] = bool(vars["hw_to_win"].get())
        cfg["windows_to_hardware"] = bool(vars["win_to_hw"].get())


PLUGIN = MicMuteMirrorPlugin()
