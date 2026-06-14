"""Probe the headset battery framing.

Sends the Bragi read-property command for battery (propID 0x0F) on the command
channel and dumps the RAW HID response, with candidate value interpretations at
every offset, so we can pin down BATTERY_VALUE_OFFSET in core/devices.py.

Run with the headset ON and AWAKE (not in standby), and ideally with the tray
app quit so nothing else holds the HID channel:

    python dev_probes\probe_battery.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pywinusb.hid as hid
from signal_companion.core import devices as dev


def open_cmd(spec):
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


def main():
    spec = dev.resolve_headset("auto") or dev.SUPPORTED_HEADSETS.get("virtuoso_xt")
    if not spec:
        print("no supported headset found"); return
    print("device:", spec["label"], "| present:", dev._is_present(spec["vid"], spec["pid"]))

    device = open_cmd(spec)
    if not device:
        print("could not open command channel — headset off/asleep, or another app "
              "(SignalRGB / the tray) holds it. Quit the tray and wake the headset.")
        return

    reports = []
    device.set_raw_data_handler(lambda d: reports.append(list(d)))

    outs = device.find_output_reports()
    if not outs:
        print("no output reports on command channel"); device.close(); return
    out = outs[0]
    out_len = device.hid_caps.output_report_byte_length or 65
    pid = dev.BATTERY_PROP_ID  # 0x0F (battery level)

    # Exact framing from the working SignalRGB headset plugin:
    #   packet = [0x02, headsetMode, 0x02, 0x0F, 0x00]; value = data.slice(4,7) LE / 10
    for mode_name, mode in (("wireless 0x09", 0x09), ("wired 0x08", 0x08)):
        cmd = [0x02, mode, 0x02, pid, 0x00]
        reports.clear()
        payload = bytearray(out_len)
        for i, b in enumerate(cmd):
            if i < out_len:
                payload[i] = b
        print(f"\n>>> {mode_name}: " + " ".join(f"{x:02x}" for x in cmd))
        try:
            out.set_raw_data(list(payload))
            out.send()
        except Exception as e:
            print("   send failed:", e); continue
        time.sleep(1.5)
        seen = {}
        for r in reports:
            sig = " ".join(f"{b:02x}" for b in r[:10])
            seen[sig] = seen.get(sig, 0) + 1
        print(f"   {len(reports)} report(s), {len(seen)} distinct:")
        for sig, n in seen.items():
            b = [int(x, 16) for x in sig.split()]
            val = (b[4] | (b[5] << 8) | (b[6] << 16)) if len(b) > 6 else None
            pct = round(val / 10.0, 1) if val is not None else None
            print(f"     x{n:<3} {sig}   slice4:7/10 = {pct}%")

    device.close()


if __name__ == "__main__":
    main()
