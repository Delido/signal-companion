"""Enumerate ALL output reports on the Virtuoso XT command channel(s).
pywinusb's hid_caps.output_report_byte_length is the MAX across all reports
of a collection. If there are multiple, picking reports[0] may hit the
wrong one. List each with its ID and size."""
import pywinusb.hid as hid

VID, PID = 0x1B1C, 0x0A64

for d in hid.HidDeviceFilter(vendor_id=VID, product_id=PID).get_devices():
    try:
        d.open()
        caps = d.hid_caps
        if caps and caps.usage_page == 0xFF42 and caps.usage == 0x0001:
            print(f"\nCollection: usage_page=0xff42 usage=0x0001")
            print(f"  path: {d.device_path}")
            print(f"  max in: {caps.input_report_byte_length}  max out: {caps.output_report_byte_length}")
            outs = d.find_output_reports()
            print(f"  Output reports ({len(outs)}):")
            for r in outs:
                rid = getattr(r, "report_id", "?")
                sz = getattr(r, "_raw_report_size", "?")
                print(f"    report_id={rid}  raw_size={sz}  type={type(r).__name__}")
                # Show the report's data structure if accessible
                try:
                    print(f"      get_raw_data initial: {r.get_raw_data()[:8]}...")
                except Exception:
                    pass
    finally:
        try: d.close()
        except: pass
