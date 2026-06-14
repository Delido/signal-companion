"""Enumerate Corsair Virtuoso XT Wireless HID interfaces and watch for
mic-mute state changes.

Protocol (extracted from Corsair_Headset_Controller.js drainPassiveEvents):
The headset pushes events on the iCUE alternate collection (usage_page=0xff42,
usage=0x0002, collection=0x0006). Event format: `03 01 01 <reg> 00 <V>`.
Mic state events use reg=0x46 for Virtuoso XT (0xA6 for HS80). V: 0=unmuted, 1=muted.
"""
import time
import pywinusb.hid as hid

VID = 0x1B1C
PID = 0x0A64  # Virtuoso XT Wireless
TARGET_USAGE_PAGE = 0xFF42  # iCUE vendor-specific
# We probe BOTH alt-collections (0x0002 for events, 0x0001 for command)
MIC_REGISTER = 0x46


def enumerate_interfaces():
    devices = hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices()
    print(f"Found {len(devices)} interface(s) with VID=0x{VID:04x} PID=0x{PID:04x}:\n")
    for d in devices:
        try:
            d.open()
            caps = d.hid_caps
            if caps is None:
                print(f"  path={d.device_path}  (no caps)")
            else:
                print(
                    f"  path={d.device_path}\n"
                    f"      usage_page=0x{caps.usage_page:04x}  usage=0x{caps.usage:04x}"
                    f"  in={caps.input_report_byte_length}  out={caps.output_report_byte_length}"
                )
        except Exception as e:
            print(f"  path={d.device_path}  (open failed: {e})")
        finally:
            try:
                d.close()
            except Exception:
                pass
    return devices


def find_event_interface(devices):
    """The plugin uses usage_page=0xff42, usage=0x0002 for the passive-event
    channel. That's where mic mute state changes show up."""
    for d in devices:
        try:
            d.open()
            caps = d.hid_caps
            if caps and caps.usage_page == TARGET_USAGE_PAGE and caps.usage == 0x0002:
                return d
            d.close()
        except Exception:
            try:
                d.close()
            except Exception:
                pass
    return None


def main():
    devices = enumerate_interfaces()
    print()

    iface = find_event_interface(devices)
    if not iface:
        print("[!] Event interface (usage_page=0xff42 usage=0x0002) not found.")
        print("    Either headset is offline (dongle disconnected) or PID differs.")
        return

    print(f"[+] Listening on event interface: {iface.device_path}")
    print("[+] Press the hardware mute button on the headset…  (Ctrl-C to exit)\n")

    last_seen = {"mic": None}

    def on_report(data):
        # data[0] is the HID report ID byte. Wire payload starts at data[1].
        # Event format: 03 01 01 <reg> 00 <V> → so wire bytes [0..5].
        if len(data) < 7:
            return
        if data[1] == 0x03 and data[2] == 0x01 and data[3] == 0x01:
            reg = data[4]
            val = data[6]
            if reg == MIC_REGISTER:
                if val != last_seen["mic"]:
                    last_seen["mic"] = val
                    print(f"  [event] mic mute = {'MUTED' if val == 1 else 'UNMUTED'}")
            else:
                print(f"  [event] reg=0x{reg:02x} val=0x{val:02x} (other)")

    iface.set_raw_data_handler(on_report)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[+] Done.")
    finally:
        iface.close()


if __name__ == "__main__":
    main()
