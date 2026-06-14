"""Smoke test: read the Windows default microphone mute state via Core Audio.

Uses pycaw's high-level helper which wraps IMMDeviceEnumerator + IAudioEndpointVolume.
GetMicrophone() returns the default capture device wrapped as an AudioDevice; we then
Activate the endpoint-volume interface on it to read the mute bit.
"""
from comtypes import CLSCTX_ALL, POINTER, cast
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume


def get_default_mic_endpoint_volume():
    mic = AudioUtilities.GetMicrophone()  # already an IMMDevice pointer
    interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def main():
    vol = get_default_mic_endpoint_volume()
    muted = bool(vol.GetMute())
    print(f"Default microphone: {'MUTED' if muted else 'UNMUTED'}")


if __name__ == "__main__":
    main()
