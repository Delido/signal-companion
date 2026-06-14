"""Active poll: send mic-state query to Virtuoso XT command channel and read
the response. Mirrors the SignalRGB plugin's fetchMicStatus path.

Query format (Virtuoso XT Wireless):
    write: [02 09 02 46 00 ...padded to 64...]
    read response prefix: [01 01 02 ?? V ...] where V at byte 4 = mic state (0=unmuted, 1=muted)
"""
import time
import pywinusb.hid as hid

VID = 0x1B1C
PID = 0x0A64
WIRELESS_MODE = 0x09  # vs 0x08 for wired
MIC_REGISTER = 0x46   # vs 0xA6 for HS80


def find_command_channel():
    for d in hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices():
        try:
            d.open()
            caps = d.hid_caps
            if caps and caps.usage_page == 0xFF42 and caps.usage == 0x0001:
                return d
            d.close()
        except Exception:
            try:
                d.close()
            except Exception:
                pass
    return None


def main():
    iface = find_command_channel()
    if not iface:
        print("[!] Command channel not found")
        return

    print(f"[+] Opened {iface.device_path}")

    # Build the query packet on the output report
    out_reports = iface.find_output_reports()
    if not out_reports:
        print("[!] No output reports")
        iface.close()
        return
    report = out_reports[0]
    out_len = iface.hid_caps.output_report_byte_length

    payload = bytearray(out_len)
    # Byte 0 = report id (0x00 unnumbered). Wire bytes start at index 1.
    wire = [0x02, WIRELESS_MODE, 0x02, MIC_REGISTER, 0x00]
    for i, b in enumerate(wire, start=1):
        if i >= out_len:
            break
        payload[i] = b

    received = []

    def handler(data):
        received.append(list(data))

    iface.set_raw_data_handler(handler)

    print(f"[+] Query: {' '.join(f'{b:02x}' for b in wire)}")
    report.set_raw_data(list(payload))
    ok = report.send()
    print(f"[+] Sent: {ok}")

    # Wait up to 500ms for response
    deadline = time.time() + 0.5
    while time.time() < deadline and not received:
        time.sleep(0.02)

    iface.close()

    if not received:
        print("[!] No response (timeout)")
        return

    for r in received:
        head = " ".join(f"{b:02x}" for b in r[:10])
        print(f"  Reply: {head}...")
        # Response format from plugin: report[0]=01 report[1]=01 report[2]=02 report[4]=state
        # But report[0] is the HID report ID byte that pywinusb prepends. Wire bytes start at index 1.
        if len(r) >= 6 and r[1] == 0x01 and r[2] == 0x01 and r[3] == 0x02:
            state = r[5]
            print(f"  → mic state: {'MUTED' if state == 1 else 'UNMUTED'}")


if __name__ == "__main__":
    main()
