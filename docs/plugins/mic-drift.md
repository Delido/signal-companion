# Mic Drift Logger

> id: `mic-drift` · version 2.0.0

A background **diagnostic** for the "my mic suddenly got twice as loud" class of
bug. It snapshots the Windows default-microphone state on an interval and logs
every unexpected change.

!!! note "Off by default"
    This plugin is disabled until you turn it on — it's a debugging tool, not an
    everyday feature.

## What it captures

Each tick it records and diffs:

- the default capture **device id** (catches the default device switching),
- master **volume scalar** (the slider, 0..1) and **dB** level,
- **mute** state,
- the device's **registry** values under
  `HKLM\…\MMDevices\Audio\Capture\<id>\FxProperties` and `\Properties`.

Any transition is written to `watcher.log` with a `[mic_drift]` prefix, showing
old → new values. Nothing is published to the EventBus — this plugin only logs.

## Settings

| Setting | Default | Notes |
|---|---|---|
| Enable diagnostic logging | off | Turn on only while investigating. |
| Poll interval (seconds) | 5.0 | Minimum 1.0 s. |

There's also an **Open log folder** button in the tab.

## Config keys

```json
"mic-drift": {
  "enabled": false,
  "poll_interval_seconds": 5.0
}
```

## Cost

One audio-endpoint read plus one registry walk per interval. Negligible at the
default 5 s, but there's no reason to leave it on once you've caught the
culprit. pycaw's noisy "COMError getting property 68/69" warnings are suppressed.

## Reading the log

```
[mic_drift] watching — scalar=0.74 dB=-7.2 muted=False regKeys=42
[mic_drift] SLIDER 0.74 → 1.0
[mic_drift] REG FxProperties\{...},5:
[mic_drift]     old: 0a00...
[mic_drift]     new: 0f00...
```

The first line is the baseline; every later line is a change it detected.
