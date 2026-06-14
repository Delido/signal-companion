"""Diagnostic logger: every N seconds, snapshot ALL parameters that could
plausibly drift on a USB-audio device (default mic) and log them to disk.

Run this in a terminal, then trigger the bug (reload SignalRGB, disconnect
headset, etc.). Watch the timestamped log to see WHICH value changed —
then we know whether to fix the slider, the boost, or something else.

Captured per tick:
  - Device friendly name + GUID  (catches "default device changed")
  - Master volume scalar (0-1, the slider position)
  - Master volume level in dB
  - dB range (min..max..step)
  - Mute state
  - Registry FxProperties under MMDevices\\Audio\\Capture — this is where
    audio drivers stash boost / processing effects per-device. Each property
    key is a {GUID},N pair. The value that changes when you toggle "Mic
    Boost +20dB" in the Levels tab will be in here.

Output:
  console + %APPDATA%\\CorsairCompanion\\mic_drift.log
"""
import logging
import os
import sys
import time
import warnings
from pathlib import Path

# Suppress pycaw's pollute-stderr warnings about devices that don't expose
# every property page. We hit them per-poll because GetAllDevices walks all
# audio endpoints; the warnings don't indicate anything wrong with OUR mic.
warnings.filterwarnings("ignore", category=UserWarning, module="pycaw.utils")

# Suppress "Exception ignored in <function _compointer_base.__del__>:
# ValueError: COM method call without VTable" — harmless GC fallout from
# comtypes when AudioUtilities.GetAllDevices() wrappers go out of scope and
# their underlying IMMDevice pointers can't reach a VTable at release time.
# Functional behaviour is unaffected; we only silence the printed noise.
def _swallow_vtable(unraisable):
    exc = unraisable.exc_value
    if isinstance(exc, ValueError) and "VTable" in str(exc):
        return
    sys.__unraisablehook__(unraisable)
sys.unraisablehook = _swallow_vtable

import comtypes
import winreg
from comtypes import CLSCTX_ALL, POINTER, cast
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

POLL_SECONDS = 1.0
APP_DATA = Path(os.getenv("APPDATA", str(Path.home()))) / "CorsairCompanion"
LOG_PATH = APP_DATA / "mic_drift.log"
APP_DATA.mkdir(parents=True, exist_ok=True)

MMDEVICES_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"


# Friendly-name lookup is expensive (walks all audio endpoints) AND noisy
# (other devices may not expose the property page). Cache per device-id and
# only re-resolve when the default mic changes.
_name_cache = {}


def _resolve_friendly_name(dev_id):
    if dev_id in _name_cache:
        return _name_cache[dev_id]
    name = "<unknown>"
    try:
        for d in AudioUtilities.GetAllDevices():
            if d.id == dev_id:
                name = d.FriendlyName or "<unnamed>"
                break
    except Exception:
        pass
    _name_cache[dev_id] = name
    return name


def get_default_mic_info():
    """Returns (id_str, friendly_name, IAudioEndpointVolume) for default mic.
    pycaw's GetMicrophone() returns the raw IMMDevice pointer without the
    AudioDevice wrapper, so the friendly name has to be resolved separately."""
    mic = AudioUtilities.GetMicrophone()
    dev_id = mic.GetId()
    name = _resolve_friendly_name(dev_id)
    interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    vol = cast(interface, POINTER(IAudioEndpointVolume))
    return dev_id, name, vol


def _read_subkey_values(full_key_path):
    """Enumerate all values under a registry subkey; render as dict."""
    result = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, full_key_path) as k:
            i = 0
            while True:
                try:
                    name, value, vtype = winreg.EnumValue(k, i)
                except OSError:
                    break
                if isinstance(value, bytes):
                    result[name] = value.hex()
                else:
                    result[name] = repr(value)
                i += 1
    except FileNotFoundError:
        pass
    except OSError as e:
        result["<error>"] = repr(e)
    return result


def read_device_registry(device_id):
    """Read EVERY registry value under the device's MMDevices entry — covers
    FxProperties AND the larger Properties subkey where boost / level
    settings hide. Returns a flat dict prefixed with the subkey name."""
    if "}." not in device_id:
        return {}
    suffix = device_id.split("}.", 1)[1]  # = "{guid}"
    base = f"{MMDEVICES_BASE}\\{suffix}"
    out = {}
    for sub in ("FxProperties", "Properties"):
        for k, v in _read_subkey_values(f"{base}\\{sub}").items():
            out[f"{sub}\\{k}"] = v
    return out


def main():
    comtypes.CoInitialize()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH), mode="a", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("=" * 80)
    logging.info(f"probe_mic_drift START — output: {LOG_PATH}")
    logging.info("trigger your repro (SignalRGB reload / unplug headset / etc.) and watch")
    logging.info("=" * 80)

    last_snapshot = None
    while True:
        try:
            dev_id, name, vol = get_default_mic_info()
            scalar = vol.GetMasterVolumeLevelScalar()
            db = vol.GetMasterVolumeLevel()
            min_db, max_db, step_db = vol.GetVolumeRange()
            muted = bool(vol.GetMute())
            reg = read_device_registry(dev_id)

            snapshot = (
                dev_id, name, round(scalar, 4), round(db, 2),
                round(min_db, 2), round(max_db, 2), round(step_db, 4),
                muted, tuple(sorted(reg.items())),
            )

            if snapshot != last_snapshot:
                if last_snapshot is None:
                    logging.info(f"INITIAL  device={name!r}  id={dev_id}")
                    logging.info(f"         scalar={scalar:.4f}  master_dB={db:.2f}  range=[{min_db}..{max_db}, step {step_db}]  muted={muted}")
                    logging.info(f"         registry: {len(reg)} value(s) under FxProperties+Properties (logged on change only)")
                else:
                    prev_dev_id, prev_name, prev_scalar, prev_db, *_, prev_reg = last_snapshot
                    if (prev_dev_id, prev_name) != (dev_id, name):
                        logging.warning(f"DEVICE CHANGED: {prev_name!r} ({prev_dev_id}) → {name!r} ({dev_id})")
                    if prev_scalar != snapshot[2]:
                        logging.warning(f"SLIDER changed: {prev_scalar} → {snapshot[2]}")
                    if prev_db != snapshot[3]:
                        logging.warning(f"MASTER dB changed: {prev_db} → {snapshot[3]}")
                    if snapshot[7] != last_snapshot[7]:
                        logging.warning(f"MUTE changed: {last_snapshot[7]} → {snapshot[7]}")
                    prev_reg_dict = dict(prev_reg)
                    cur_reg_dict = dict(snapshot[8])
                    for k in sorted(set(prev_reg_dict) | set(cur_reg_dict)):
                        if prev_reg_dict.get(k) != cur_reg_dict.get(k):
                            logging.warning(f"REG {k} changed:")
                            logging.warning(f"     old: {prev_reg_dict.get(k)}")
                            logging.warning(f"     new: {cur_reg_dict.get(k)}")
                last_snapshot = snapshot
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            logging.info("probe_mic_drift STOP")
            break
        except Exception:
            logging.exception("snapshot failed; will retry")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
