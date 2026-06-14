"""Quick attach-test: open the Virtuoso XT event channel and see if pywinusb
can hand us reports asynchronously. Runs for 5s — press the headset mute
button during that window to see live events."""
import time
import pywinusb.hid as hid

VID = 0x1B1C
PID = 0x0A64


def main():
    devices = hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices()
    target = None
    for d in devices:
        try:
            d.open()
            caps = d.hid_caps
            if caps and caps.usage_page == 0xFF42 and caps.usage == 0x0002:
                target = d
                break
            d.close()
        except Exception:
            try:
                d.close()
            except Exception:
                pass

    if not target:
        print("[!] Event channel not found")
        return

    print(f"[+] Opened {target.device_path}")
    print("[+] Watching for 5 seconds — press headset mute button now...")

    received = []

    def handler(data):
        # First byte is the HID report ID (typically 0x00).
        # Wire payload starts at data[1].
        received.append(list(data))
        if len(data) >= 7 and data[1] == 0x03 and data[2] == 0x01 and data[3] == 0x01:
            reg = data[4]
            val = data[6]
            label = "mic" if reg == 0x46 else f"reg=0x{reg:02x}"
            print(f"  [{time.strftime('%H:%M:%S')}] event: {label} val=0x{val:02x}")
        else:
            head = " ".join(f"{b:02x}" for b in data[:10])
            print(f"  [{time.strftime('%H:%M:%S')}] other report: {head}...")

    target.set_raw_data_handler(handler)
    time.sleep(5)
    target.close()

    print(f"\n[+] Done — received {len(received)} report(s) total.")


if __name__ == "__main__":
    main()
