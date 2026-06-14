"""Device registry — single source of truth for supported peripherals.

Each entry captures USB IDs plus device-specific protocol constants the
plugins need. Adding a supported device = one entry here; its UI dropdown
option appears automatically via *_choices().

`auto` selection picks the first listed entry whose USB IDs are present.
Users can override per-plugin to force a specific device or `none`.
"""
import logging

import pywinusb.hid as hid


# ── Keyboards (Game Mode plugin) ─────────────────────────────────────────────
SUPPORTED_KEYBOARDS = {
    "vanguard_pro_96": {
        "label": "Corsair Vanguard Pro 96",
        "vid": 0x1B1C,
        "pid": 0x2B0E,
        "usage_page": 0xFF42,
        "usage": 0x0001,
    },
}

# ── Headsets (Mic Mute Mirror + Battery Alert plugins) ───────────────────────
SUPPORTED_HEADSETS = {
    "virtuoso_xt": {
        "label": "Corsair Virtuoso XT Wireless",
        "vid": 0x1B1C,
        "pid": 0x0A64,
        "event_usage_page": 0xFF42,
        "event_usage": 0x0002,    # col06 — passive event channel
        "cmd_usage_page": 0xFF42,
        "cmd_usage": 0x0001,      # col05 — command channel
        "mic_register": 0x46,
        "led_echo_register": 0x8E,
        "wireless_mode": 0x09,    # vs 0x08 for wired
        "supports_battery": True,
    },
    # Future: HS80 (mic_register=0xA6, different PID), wired Virtuoso etc.
}

# Bragi battery read, verified against the working SignalRGB headset plugin
# (Corsair_Headset_Controller.js) and confirmed live via dev_probes/probe_battery.py:
#   command  = [0x02, <wireless_mode>, 0x02, 0x0F, 0x00]   (report-id 0x02 +
#              conn byte + read-opcode 0x02 + propID 0x0F battery level)
#   response = the input report whose byte[2] == 0x02 (read-opcode echo); the
#              device also spams periodic notifications with byte[2] == 0x06.
#   value    = bytes[4..6] little-endian, in units of 0.1% (so /10 = percent).
BATTERY_PROP_ID = 0x0F
BATTERY_READ_OPCODE = 0x02         # response byte[2] echoes this on a real read
BATTERY_VALUE_OFFSET = 4          # response[4:7] little-endian, units of 0.1%


def battery_read_cmd(spec):
    """Bragi battery-level read command for this headset (report-id 0x02)."""
    return [0x02, spec.get("wireless_mode", 0x09), 0x02, BATTERY_PROP_ID, 0x00]


def _is_present(vid: int, pid: int) -> bool:
    return bool(hid.HidDeviceFilter(vendor_id=vid, product_id=pid).get_devices())


def resolve_keyboard(config_key: str):
    return _resolve(config_key, SUPPORTED_KEYBOARDS, "keyboard")


def resolve_headset(config_key: str):
    return _resolve(config_key, SUPPORTED_HEADSETS, "headset")


def _resolve(config_key, table, kind):
    if config_key == "none":
        return None
    if config_key == "auto":
        for key, spec in table.items():
            if _is_present(spec["vid"], spec["pid"]):
                logging.info(f"[devices] {kind} auto → {key}")
                return spec
        return None
    return table.get(config_key)


def keyboard_choices():
    return _choices(SUPPORTED_KEYBOARDS)


def headset_choices():
    return _choices(SUPPORTED_HEADSETS)


def _choices(table):
    """For UI dropdowns: [(key, label)] including auto + none."""
    return [("auto", "Auto-detect"), ("none", "Disabled")] + [
        (k, v["label"]) for k, v in table.items()
    ]


def choice_label_for_key(choices, key):
    """[(key,label)] + key -> label, defaulting to the first entry's label."""
    for k, label in choices:
        if k == key:
            return label
    return choices[0][1] if choices else key


def choice_key_for_label(choices, label):
    """[(key,label)] + label -> key, defaulting to the first entry's key."""
    for k, lbl in choices:
        if lbl == label:
            return k
    return choices[0][0] if choices else ""


def _open_command_channel(spec):
    """Open the headset command-channel HID interface (usage_page/usage from
    spec). Returns an opened device or None. Caller must close()."""
    for d in hid.HidDeviceFilter(vendor_id=spec["vid"], product_id=spec["pid"]).get_devices():
        try:
            d.open()
            caps = d.hid_caps
            if (caps and caps.usage_page == spec["cmd_usage_page"]
                    and caps.usage == spec["cmd_usage"]):
                return d
            d.close()
        except Exception:
            try:
                d.close()
            except Exception:
                pass
    return None


def read_battery(spec):
    """Read headset battery as an integer percent (0..100), or None on failure
    / unsupported. Uses the Bragi read-property roundtrip on the command
    channel — same numbered-report conn pattern the mic-mute writer uses.

    NOTE: response parsing is probe-verified (see BATTERY_* constants and
    dev_probes/probe_battery.py)."""
    if not spec or not spec.get("supports_battery"):
        return None
    device = _open_command_channel(spec)
    if device is None:
        return None
    try:
        reports = device.find_output_reports()
        if not reports:
            return None
        report = reports[0]
        out_len = device.hid_caps.output_report_byte_length or 65
        # Start listening BEFORE sending — the headset also spams periodic
        # notifications, so we collect a window of reports and pick the real
        # read response (byte[2] == read-opcode), not just the first one.
        responses = _listen_input(device)
        payload = bytearray(out_len)
        for i, b in enumerate(battery_read_cmd(spec)):
            if i >= out_len:
                break
            payload[i] = b
        report.set_raw_data(list(payload))
        if not report.send():
            return None
        import time as _t
        _t.sleep(1.0)                      # let the response arrive among the noise
        for data in list(responses):
            if (len(data) > BATTERY_VALUE_OFFSET + 2
                    and data[2] == BATTERY_READ_OPCODE):
                raw = (data[BATTERY_VALUE_OFFSET]
                       | (data[BATTERY_VALUE_OFFSET + 1] << 8)
                       | (data[BATTERY_VALUE_OFFSET + 2] << 16))
                percent = round(raw / 10.0)
                if 0 <= percent <= 100:
                    return percent
        return None
    except Exception:
        logging.exception("[devices] read_battery failed")
        return None
    finally:
        try:
            device.close()
        except Exception:
            pass


def _listen_input(device):
    """Start capturing all input reports from a command-channel device into a
    list (pywinusb delivers them via a handler callback). Returns the list,
    which fills as reports arrive."""
    captured = []
    device.set_raw_data_handler(lambda data: captured.append(list(data)))
    return captured
