# Devices

`core/devices.py` is the **single source of truth** for supported peripherals.
Each entry captures the USB IDs plus the device-specific protocol constants the
plugins need. Adding a supported device is one entry here — its dropdown option
then appears automatically in every relevant plugin's settings tab.

## Selection model

Each device-using plugin has a `device` config key:

- `auto` — pick the first listed entry whose USB IDs are actually present.
- `none` — disable the plugin's device side.
- a specific key (e.g. `virtuoso_xt`) — force that device.

The UI dropdowns are generated from the registry via `*_choices()`, always
prefixed with **Auto-detect** and **Disabled**.

## Supported keyboards

Used by [Game Mode](plugins/game-mode.md).

| Key | Label | VID | PID | usage_page / usage |
|---|---|---|---|---|
| `vanguard_pro_96` | Corsair Vanguard Pro 96 | `0x1B1C` | `0x2B0E` | `0xFF42` / `0x0001` (command) |

## Supported headsets

Used by [Mic Mute Mirror](plugins/mic-mute-mirror.md) and
[Battery Alert](plugins/battery-alert.md).

| Key | Label | VID | PID | Battery |
|---|---|---|---|---|
| `virtuoso_xt` | Corsair Virtuoso XT Wireless | `0x1B1C` | `0x0A64` | yes |

Per-headset protocol constants (Virtuoso XT):

| Field | Value | Meaning |
|---|---|---|
| `event_usage_page` / `event_usage` | `0xFF42` / `0x0002` | col06 — passive event channel (mute button) |
| `cmd_usage_page` / `cmd_usage` | `0xFF42` / `0x0001` | col05 — command channel (writes) |
| `mic_register` | `0x46` | mic mute register |
| `led_echo_register` | `0x8E` | mute-LED echo register |
| `wireless_mode` | `0x09` | connection-mode byte (wired = `0x08`) |
| `supports_battery` | `true` | enables Battery Alert |

## Battery read (Bragi)

Battery uses the Bragi v2 "read property" roundtrip on the command channel:

```python
BATTERY_PROP_ID     = 0x0F                       # confirmed
BATTERY_READ_CMD    = [0x00, 0x00, 0x02, 0x0F, 0x00]
BATTERY_VALUE_OFFSET = 4    # response[4:6] little-endian, units of 0.1%
```

`read_battery(spec)` sends the command, captures one input report via a
pywinusb raw-data handler, and decodes `response[offset:offset+2]` as a
little-endian value in units of 0.1 %, rounded to an integer percent.

!!! warning "Open verification gate"
    `BATTERY_PROP_ID` (`0x0F`) is confirmed against Corsair's
    `Corsair_Bragi_Device.js`. The **response offset** is a best guess until
    validated on the live headset with `dev_probes/probe_battery.py`. If the
    probe shows a different layout, fix only `BATTERY_READ_CMD` /
    `BATTERY_VALUE_OFFSET`. See [Development](development.md#verification-gates).

## Adding a device

1. Add one entry to `SUPPORTED_KEYBOARDS` or `SUPPORTED_HEADSETS` with the USB
   IDs and protocol constants.
2. That's it — the dropdown option appears in the relevant plugin tabs, and
   `auto` will pick it up when present.

Use the scripts in `dev_probes/` to reverse-engineer the HID framing for a new
device before adding it. See [Development](development.md#dev-probes).
