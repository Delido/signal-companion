"""Per-thread COM apartment initialization.

pywinusb's raw-data handler runs on its own worker thread that has NOT called
CoInitialize; any pycaw/comtypes call from there raises
OSError [-2147221008]. Call _ensure_com_initialized() at the entry of any
function that touches COM from a non-main thread.
"""
import threading

import comtypes

_com_init = threading.local()


def ensure_com_initialized():
    if not getattr(_com_init, "done", False):
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        _com_init.done = True
