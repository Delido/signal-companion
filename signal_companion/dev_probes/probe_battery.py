"""Probe: read the Virtuoso XT battery level over the command channel.

VERIFICATION GATE for the battery_alert plugin. We send the Bragi
read-property command for batteryLevel (propID 0x0F) and dump the raw
response so we can confirm where the 16-bit value lands before trusting
core.devices.read_battery().

Run with the headset powered on and the dongle connected:
    python probe_battery.py

What to look for in the dump: a 16-bit little-endian field whose value/10
matches the battery percentage iCUE shows (e.g. 0x02 0x03 = 0x0302 = 770 →
77%). If the offset differs from BATTERY_VALUE_OFFSET (4), update the
BATTERY_* constants in signal_companion/core/devices.py.
"""
import threading
import time

import pywinusb.hid as hid

VID = 0x1B1C
PID = 0x0A64                 # Virtuoso XT Wireless
CMD_USAGE_PAGE = 0xFF42
CMD_USAGE = 0x0001           # col05 — command channel
BATTERY_PROP_ID = 0x0F

# Candidate read commands to try; the Bragi read opcode is 0x02. We try a few
# framings since the exact wrapper varies by collection.
CANDIDATES = [
    [0x00, 0x00, 0x02, BATTERY_PROP_ID, 0x00],
    [0x00, 0x00, 0x09, 0x02, BATTERY_PROP_ID, 0x00],   # wireless-mode framed
    [0x02, 0x09, 0x02, BATTERY_PROP_ID, 0x00],         # numbered-report framed
]


def open_cmd_channel():
    for d in hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices():
        try:
            d.open()
            caps = d.hid_caps
            if caps and caps.usage_page == CMD_USAGE_PAGE and caps.usage == CMD_USAGE:
                print(f"[+] command channel: {d.device_path}")
                print(f"    in={caps.input_report_byte_length} out={caps.output_report_byte_length}")
                return d
            d.close()
        except Exception as e:
            print(f"    open failed: {e}")
            try:
                d.close()
            except Exception:
                pass
    return None


def main():
    dev = open_cmd_channel()
    if not dev:
        print("[!] command channel not found — headset offline or PID differs.")
        return

    captured = {"data": None}
    got = threading.Event()

    def handler(data):
        captured["data"] = list(data)
        got.set()

    dev.set_raw_data_handler(handler)

    out_reports = dev.find_output_reports()
    if not out_reports:
        print("[!] no output reports on command channel.")
        dev.close()
        return
    report = out_reports[0]
    out_len = dev.hid_caps.output_report_byte_length or 65

    try:
        for cmd in CANDIDATES:
            captured["data"] = None
            got.clear()
            payload = bytearray(out_len)
            for i, b in enumerate(cmd):
                if i < out_len:
                    payload[i] = b
            report.set_raw_data(list(payload))
            ok = report.send()
            print(f"\n[>] sent {['%02x' % b for b in cmd]} send()={ok}")
            if got.wait(0.7) and captured["data"]:
                d = captured["data"]
                head = " ".join(f"{b:02x}" for b in d[:16])
                print(f"[<] response[0:16]: {head}")
                for off in range(2, min(12, len(d) - 1)):
                    val = d[off] | (d[off + 1] << 8)
                    if 0 < val <= 1000:
                        print(f"      offset {off}: 0x{val:04x} = {val} → {val/10:.0f}% ?")
            else:
                print("[<] no response within 0.7s")
            time.sleep(0.3)
    finally:
        dev.close()
        print("\n[+] done. Update BATTERY_* in core/devices.py to the matching framing/offset.")


if __name__ == "__main__":
    main()
