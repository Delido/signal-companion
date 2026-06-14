"""One-shot probe: enumerate the Corsair Vanguard Pro 96 HID interfaces and
write the Game Mode setProperty(0xE1) packet directly.

Wire bytes (matches what the SignalRGB plugin sends in setHardwareGameMode):
    00 01 02 01 E1 00 <0|1>
prefixed by the HID report-ID byte (0x00) when handed to pywinusb's send_feature_report
or set_raw_data.

Strategy: walk all HID interfaces of VID=0x1b1c, PID=0x2B0E and try the
"command/property" interface — the same one SignalRGB selects via
set_endpoint(0x02, 0x01, 0xFF42). On Bragi-v2 keyboards that's usage_page=0xFF42.
"""
import sys
import pywinusb.hid as hid

VID = 0x1b1c
PID = 0x2B0E  # Vanguard Pro 96
TARGET_USAGE_PAGE = 0xFF42  # Bragi-v2 vendor-specific command page
TARGET_USAGE      = 0x0001  # command (write) channel; usage 0x0002 = notifications (read-only)


def enumerate_keyboard():
    devices = hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices()
    if not devices:
        print(f"[!] No device found with VID=0x{VID:04x} PID=0x{PID:04x}", file=sys.stderr)
        sys.exit(2)
    print(f"[+] Found {len(devices)} interface(s):")
    for d in devices:
        try:
            d.open()
            caps = d.hid_caps
            print(f"    path={d.device_path}")
            if caps is None:
                print("        (no hid_caps even after open)")
            else:
                print(f"        usage_page=0x{caps.usage_page:04x}  usage=0x{caps.usage:04x}  "
                      f"input_size={caps.input_report_byte_length}  "
                      f"output_size={caps.output_report_byte_length}")
        except Exception as e:
            print(f"    path={d.device_path}  [open failed: {e}]")
        finally:
            try:
                d.close()
            except Exception:
                pass
    return devices


def find_command_iface(devices):
    for d in devices:
        try:
            d.open()
            caps = d.hid_caps
            if caps and caps.usage_page == TARGET_USAGE_PAGE and caps.usage == TARGET_USAGE:
                # Leave it open for write
                return d
            d.close()
        except Exception:
            try:
                d.close()
            except Exception:
                pass
    return None


def send_game_mode(device, enabled: bool):
    # Wire bytes are: 00 01 02 01 E1 00 <V>
    # We pad to output_report_byte_length so write succeeds.
    out_len = device.hid_caps.output_report_byte_length
    if out_len <= 0:
        # Some interfaces use feature reports; fall back to 64-byte default.
        out_len = 65
    payload = bytearray(out_len)
    # Byte 0 is the HID report-ID. We use 0x00 (unnumbered report).
    # Bytes 1..N are the wire data.
    wire = [0x00, 0x01, 0x02, 0x01, 0xE1, 0x00, 0x01 if enabled else 0x00]
    for i, b in enumerate(wire, start=1):
        if i >= out_len:
            break
        payload[i] = b

    reports = device.find_output_reports()
    if not reports:
        print("[!] No output reports available on this interface", file=sys.stderr)
        return False

    # Use the lowest-level write: set_raw_data + send
    report = reports[0]
    raw = list(payload[: report.report_size if hasattr(report, "report_size") else out_len])
    # pywinusb expects the first byte to be the report id
    report.set_raw_data(raw)
    ok = report.send()
    print(f"[+] Sent Game Mode = {'ON' if enabled else 'OFF'} -> success={ok}")
    return ok


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("on", "off", "0", "1"):
        print("Usage: toggle_gamemode.py {on|off}")
        sys.exit(1)
    enable = sys.argv[1] in ("on", "1")

    devices = enumerate_keyboard()
    cmd_iface = find_command_iface(devices)
    if not cmd_iface:
        print(f"[!] No interface with usage_page=0x{TARGET_USAGE_PAGE:04x} found.", file=sys.stderr)
        sys.exit(3)
    print(f"[+] Using command interface: {cmd_iface.device_path}")

    try:
        send_game_mode(cmd_iface, enable)
    finally:
        cmd_iface.close()


if __name__ == "__main__":
    main()
