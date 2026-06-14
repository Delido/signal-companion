"""Game Mode auto-toggle plugin (migrated from feature_game_mode.py).

Watches Windows processes and toggles the configured Corsair keyboard's
hardware Game Mode over USB when any whitelisted executable is running. The
SignalRGB plugin's `syncGameModeFromHardware` polling picks the change up
within ~3s and runs its dependency chain (Polling Rate + FlashTap + lighting
refresh) — no conflict because both processes share the HID device cleanly.
"""
import logging
import threading

import psutil
import pywinusb.hid as hid
import tkinter as tk
from tkinter import simpledialog, ttk

from signal_companion.core.plugin import Plugin


class KeyboardController:
    """Owns the HID handle to the keyboard's command interface, auto-reopens
    if the device disappears (USB reset, plugin reload)."""

    def __init__(self, device_spec):
        self.spec = device_spec
        self._device = None

    def _open(self):
        if not self.spec:
            return False
        self.close()
        for d in hid.HidDeviceFilter(vendor_id=self.spec["vid"], product_id=self.spec["pid"]).get_devices():
            try:
                d.open()
                caps = d.hid_caps
                if caps and caps.usage_page == self.spec["usage_page"] and caps.usage == self.spec["usage"]:
                    self._device = d
                    logging.info(f"[game_mode] Opened {self.spec['label']} command interface")
                    return True
                d.close()
            except Exception:
                try:
                    d.close()
                except Exception:
                    pass
        return False

    def set_game_mode(self, enabled: bool) -> bool:
        if not self.spec:
            return False
        if not self._device and not self._open():
            return False
        try:
            out_len = self._device.hid_caps.output_report_byte_length or 65
            payload = bytearray(out_len)
            # Wire bytes (matches SignalRGB plugin's setHardwareGameMode):
            #   00 01 02 01 E1 00 <0|1>, prefixed with HID report-ID 0x00.
            wire = [0x00, 0x00, 0x01, 0x02, 0x01, 0xE1, 0x00, 0x01 if enabled else 0x00]
            for i, b in enumerate(wire):
                if i >= out_len:
                    break
                payload[i] = b
            reports = self._device.find_output_reports()
            if not reports:
                return False
            report = reports[0]
            report.set_raw_data(list(payload))
            return bool(report.send())
        except Exception:
            logging.exception("[game_mode] write failed; will reopen next time")
            self.close()
            return False

    def close(self):
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None


class ProcessWatcher(threading.Thread):
    """Polls the process list against the whitelist; writes to the keyboard
    only on state transitions."""

    def __init__(self, keyboard, get_config, on_state_change=None):
        super().__init__(daemon=True, name="GameModeProcessWatcher")
        self.keyboard = keyboard
        self.get_config = get_config
        self.on_state_change = on_state_change
        self._stop = threading.Event()
        self.last_state = None

    def stop(self):
        self._stop.set()

    @staticmethod
    def _current_processes():
        names = set()
        for p in psutil.process_iter(["name"]):
            n = p.info.get("name")
            if n:
                names.add(n.lower())
        return names

    def run(self):
        # Join the MTA: this thread enumerates HID via ctypes and can trigger the
        # cyclic GC that frees pycaw COM objects from other plugins. See comutil.
        from signal_companion.core.comutil import ensure_com_initialized
        ensure_com_initialized()
        while not self._stop.is_set():
            section = self.get_config()
            interval = max(0.5, float(section.get("poll_interval_seconds", 2.0)))
            if section.get("enabled", True) and self.keyboard.spec:
                whitelist = {name.lower() for name in section.get("executables", []) if name}
                desired = bool(whitelist and (whitelist & self._current_processes()))
                if desired != self.last_state:
                    if self.keyboard.set_game_mode(desired):
                        self.last_state = desired
                        logging.info(f"[game_mode] → {'ON' if desired else 'OFF'}")
                        if self.on_state_change:
                            try:
                                self.on_state_change(desired)
                            except Exception:
                                logging.exception("[game_mode] state callback failed")
                    else:
                        logging.warning("[game_mode] keyboard write failed; will retry")
            self._stop.wait(interval)


class GameModePlugin(Plugin):
    id = "game-mode"
    name = "Game Mode"
    version = "2.0.0"
    description = "Auto-toggle keyboard hardware Game Mode by running process."

    def __init__(self):
        self.ctx = None
        self.keyboard = None
        self.watcher = None

    def default_config(self):
        return {
            "enabled": True,
            "device": "auto",
            "poll_interval_seconds": 2.0,
            "executables": [],
        }

    def start(self, ctx):
        self.ctx = ctx
        spec = ctx.devices.resolve_keyboard(ctx.config().get("device", "auto"))
        if spec:
            ctx.log.info(f"keyboard: {spec['label']}")
        else:
            ctx.log.info("keyboard: none (Game Mode inactive)")
        self.keyboard = KeyboardController(spec)
        self.watcher = ProcessWatcher(
            self.keyboard, get_config=ctx.config, on_state_change=self._on_change
        )
        self.watcher.start()

    def stop(self):
        if self.watcher:
            self.watcher.stop()
        if self.keyboard:
            self.keyboard.close()

    def _on_change(self, active):
        if self.ctx:
            self.ctx.set_status({
                "label": f"Game Mode: {'ON' if active else 'off'}",
                "color": (220, 50, 50) if active else (90, 90, 90),
            })
        self.ctx.events.publish("game_mode.active", active)

    # ── settings tab ──
    def build_settings_tab(self, parent, cfg):
        from signal_companion.core.devices import keyboard_choices, choice_label_for_key
        vars = {}

        enabled = tk.BooleanVar(value=cfg.get("enabled", True))
        ttk.Checkbutton(parent, text="Enable Game Mode auto-toggle", variable=enabled).pack(anchor="w", pady=(0, 6))
        vars["enabled"] = enabled

        dev_row = ttk.Frame(parent)
        dev_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(dev_row, text="Keyboard:").pack(side=tk.LEFT)
        choices = keyboard_choices()
        cur_label = choice_label_for_key(choices, cfg.get("device", "auto"))
        dev_var = tk.StringVar(value=cur_label)
        ttk.Combobox(dev_row, textvariable=dev_var, values=[l for _, l in choices],
                     state="readonly", width=30).pack(side=tk.LEFT, padx=8)
        vars["device_var"] = dev_var
        vars["device_choices"] = choices

        ttk.Label(parent, text="Executable names that trigger Game Mode\n"
                  "(case-insensitive, exact match on process name):",
                  justify="left").pack(anchor="w", pady=(8, 4))
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb = tk.Listbox(list_frame, yscrollcommand=sb.set, selectmode=tk.EXTENDED, height=8)
        for exe in cfg.get("executables", []):
            lb.insert(tk.END, exe)
        lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=lb.yview)
        vars["listbox"] = lb

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X, pady=4)

        def add_manual():
            name = simpledialog.askstring("Add Executable", "Executable name (e.g. cs2.exe):",
                                          parent=parent.winfo_toplevel())
            if name and name.strip():
                lb.insert(tk.END, name.strip())

        def add_running():
            running = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info.get("name")},
                             key=str.lower)
            dlg = tk.Toplevel(parent.winfo_toplevel())
            dlg.title("Pick running processes")
            dlg.geometry("400x460")
            dlg.transient(parent.winfo_toplevel())
            ttk.Label(dlg, text="Select one or more (Ctrl/Shift):").pack(pady=(10, 4))
            f = ttk.Frame(dlg)
            f.pack(fill=tk.BOTH, expand=True, padx=10)
            sb2 = ttk.Scrollbar(f)
            sb2.pack(side=tk.RIGHT, fill=tk.Y)
            lb2 = tk.Listbox(f, yscrollcommand=sb2.set, selectmode=tk.EXTENDED)
            for n in running:
                lb2.insert(tk.END, n)
            lb2.pack(fill=tk.BOTH, expand=True)
            sb2.config(command=lb2.yview)

            def pick():
                for i in lb2.curselection():
                    lb.insert(tk.END, lb2.get(i))
                dlg.destroy()

            bb = ttk.Frame(dlg)
            bb.pack(fill=tk.X, padx=10, pady=8)
            ttk.Button(bb, text="Add Selected", command=pick).pack(side=tk.RIGHT, padx=2)
            ttk.Button(bb, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT, padx=2)

        def remove_sel():
            for i in reversed(lb.curselection()):
                lb.delete(i)

        ttk.Button(btn_row, text="Add…", command=add_manual).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Add from Running…", command=add_running).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Remove Selected", command=remove_sel).pack(side=tk.LEFT, padx=2)

        interval_row = ttk.Frame(parent)
        interval_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(interval_row, text="Poll interval (seconds):").pack(side=tk.LEFT)
        interval = tk.StringVar(value=str(cfg.get("poll_interval_seconds", 2.0)))
        ttk.Entry(interval_row, textvariable=interval, width=8).pack(side=tk.LEFT, padx=6)
        vars["interval"] = interval
        return vars

    def save_settings(self, cfg, vars):
        from signal_companion.core.devices import choice_key_for_label
        cfg["enabled"] = bool(vars["enabled"].get())
        cfg["device"] = choice_key_for_label(vars["device_choices"], vars["device_var"].get())
        cfg["executables"] = [vars["listbox"].get(i) for i in range(vars["listbox"].size())]
        try:
            cfg["poll_interval_seconds"] = max(0.5, float(vars["interval"].get()))
        except ValueError:
            pass


PLUGIN = GameModePlugin()
