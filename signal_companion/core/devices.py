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

# Bragi v2 "read property" opcode. SetProperty writes use [.. 0x01 0x02 <prop>];
# the property *read* command is the 0x02 opcode below. battery level lives at
# propID 0x0F (confirmed against Corsair_Bragi_Device.js, which skips
# FetchProperty(0x0F) for wired keyboards "they don't have a battery").
#
# VERIFICATION GATE: the exact response offset for the 16-bit value is
# confirmed by dev_probes/probe_battery.py against the live headset before we
# rely on it. If the probe shows a different layout, fix BATTERY_* below only.
BATTERY_PROP_ID = 0x0F
BATTERY_READ_CMD = [0x00, 0x00, 0x02, BATTERY_PROP_ID, 0x00]
BATTERY_VALUE_OFFSET = 4          # response[4:6] little-endian, units of 0.1%


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
        payload = bytearray(out_len)
        for i, b in enumerate(BATTERY_READ_CMD):
            if i >= out_len:
                break
            payload[i] = b
        report.set_raw_data(list(payload))
        if not report.send():
            return None
        # Read the firmware's response on the command channel's input report.
        data = _read_input(device)
        if not data or len(data) < BATTERY_VALUE_OFFSET + 2:
            return None
        raw = data[BATTERY_VALUE_OFFSET] | (data[BATTERY_VALUE_OFFSET + 1] << 8)
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


def _read_input(device, timeout_s=0.5):
    """Grab one input report from a command-channel device. pywinusb delivers
    input reports via a handler callback; we capture the first one within the
    timeout window."""
    import threading

    captured = {"data": None}
    got = threading.Event()

    def handler(data):
        if captured["data"] is None:
            captured["data"] = data
            got.set()

    device.set_raw_data_handler(handler)
    got.wait(timeout_s)
    return captured["data"]
