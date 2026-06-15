"""Windows audio-endpoint enumeration + default-device switching.

Enumerating render (playback) endpoints uses the documented MMDevice API via
pycaw. *Setting* the default endpoint is not in the public API — Windows only
exposes it through the undocumented `IPolicyConfig` COM interface (the same one
nircmd / SoundVolumeView / EarTrumpet use). We declare just enough of its vtable
to reach `SetDefaultEndpoint`, then set all three roles (Console / Multimedia /
Communications) so a switch is complete.

All calls initialise COM (MTA) on the calling thread first — the HTTP server
handles each request on its own thread, so nothing here caches COM objects
across threads.
"""
import warnings

import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, CoCreateInstance
from ctypes.wintypes import DWORD, LPCWSTR

from pycaw.constants import CLSID_MMDeviceEnumerator
from pycaw.pycaw import AudioUtilities, DEVICE_STATE, EDataFlow, IMMDeviceEnumerator

from signal_companion.core.comutil import ensure_com_initialized

# Undocumented PolicyConfig client.
_CLSID_PolicyConfig = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")

# Render endpoint roles: eConsole, eMultimedia, eCommunications. Set all three.
_ROLES = (0, 1, 2)
_RENDER = EDataFlow.eRender.value
_MULTIMEDIA = 1  # ERole used when reading "the" default


class IPolicyConfig(comtypes.IUnknown):
    """Minimal IPolicyConfig — only SetDefaultEndpoint is called; the earlier
    methods exist solely to occupy their vtable slots in the right order."""

    _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
    _methods_ = [
        COMMETHOD([], HRESULT, name) for name in (
            "GetMixFormat", "GetDeviceFormat", "ResetDeviceFormat", "SetDeviceFormat",
            "GetProcessingPeriod", "SetProcessingPeriod", "GetShareMode", "SetShareMode",
            "GetPropertyValue", "SetPropertyValue",
        )
    ] + [
        COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                  (["in"], LPCWSTR, "wszDeviceId"),
                  (["in"], DWORD, "eRole")),
        COMMETHOD([], HRESULT, "SetEndpointVisibility"),
    ]


def _enumerator():
    return comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)


def _friendly_name(dev):
    # CreateDevice reads a bag of properties and warns on the few this endpoint
    # doesn't expose (68/69); we only want the name, so silence those warnings.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return AudioUtilities.CreateDevice(dev).FriendlyName
        except Exception:
            return dev.GetId()


def list_render_devices():
    """Active playback endpoints as [{"id", "name", "default": bool}, ...]."""
    ensure_com_initialized()
    enum = _enumerator()
    coll = enum.EnumAudioEndpoints(_RENDER, DEVICE_STATE.ACTIVE.value)
    default_id = current_default_id(enum)
    out = []
    for i in range(coll.GetCount()):
        dev = coll.Item(i)
        devid = dev.GetId()
        out.append({"id": devid, "name": _friendly_name(dev), "default": devid == default_id})
    return out


def current_default_id(enum=None):
    """Device id of the current default playback endpoint, or None."""
    ensure_com_initialized()
    enum = enum or _enumerator()
    try:
        return enum.GetDefaultAudioEndpoint(_RENDER, _MULTIMEDIA).GetId()
    except Exception:
        return None  # no active render device at all


def set_default(device_id):
    """Make `device_id` the default playback device for all three roles."""
    ensure_com_initialized()
    pc = CoCreateInstance(_CLSID_PolicyConfig, interface=IPolicyConfig, clsctx=CLSCTX_ALL)
    for role in _ROLES:
        pc.SetDefaultEndpoint(device_id, role)
