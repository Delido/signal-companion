# Mic Mute Mirror

> id: `mic-mute-mirror` · version 2.0.0

Keeps a supported headset's **hardware mute button** and the **Windows default
microphone** in sync — in both directions.

## What it does

- **Headset → Windows**: when you press the headset mute button, the plugin
  reads the event off the headset's passive HID event channel and calls
  `IAudioEndpointVolume.SetMute` on the Windows default mic.
- **Windows → Headset**: when Windows mute changes (any app, hotkey, etc.), the
  plugin pushes the state to the headset over its command channel — a paired
  SET that updates both the mute LED and the device-level audio.

Either direction can be turned off independently. The plugin publishes
`mic.muted` (`bool`) and updates the tray indicator.

## Why both directions?

Some apps (notably Discord) bypass the Windows-side mute via raw capture. The
**Windows → Headset** direction cuts the mic at the *device* level, which those
apps can't bypass. Keeping both enabled gives you a single mute that holds
everywhere.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Enable Mic Mute Mirror | on | Master switch. |
| Headset | Auto-detect | Pick a [supported headset](../devices.md), `Auto-detect`, or `Disabled`. |
| Headset button → Windows mic | on | The hardware → Windows direction. |
| Windows mic → Headset | on | The Windows → hardware direction. |

## Config keys

```json
"mic-mute-mirror": {
  "enabled": true,
  "device": "auto",
  "hardware_to_windows": true,
  "windows_to_hardware": true
}
```

## How it works (protocol)

Two HID collections on the same headset:

- **Event channel** (`event_usage_page` / `event_usage`): the plugin registers a
  raw-data handler and watches for the mute event frame
  `03 01 01 <mic_register> 00 <value>`. On this collection pywinusb does **not**
  prepend a report-ID byte, so `data[0]` is wire byte 0.
- **Command channel** (`cmd_usage_page` / `cmd_usage`): mute is pushed as a
  paired SET — first `led_echo_register`, then `mic_register`, both carrying the
  same value byte. This collection's output report is *numbered*
  (`report_id 0x02`), and that leading byte both identifies the report and is
  transmitted as the connection byte.

The Windows side caches an `IAudioEndpointVolume` on the default mic and polls
its mute state every 0.5 s. All COM use goes through
`core.comutil.ensure_com_initialized()` (per-thread COM init).

Register values and usage pages come from the [device registry](../devices.md).

## Troubleshooting

- **Button does nothing** — log shows `headset: none (Mic Mute Mirror inactive)`:
  the configured headset wasn't found, or the wrong device is selected.
- **Discord still hears me when muted in Windows** — enable
  *Windows mic → Headset* so the mic is cut at the device level.
