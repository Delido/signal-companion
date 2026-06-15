"""Process-wide COM apartment initialization (multi-threaded apartment).

pycaw/comtypes wrap COM objects whose `Release()` is invoked from `__del__`.
With CoInitialize() (a *single*-threaded apartment, STA) each worker thread gets
its own apartment, and when Python's cyclic garbage collector later frees one of
those COM objects on a DIFFERENT thread, the cross-apartment Release crashes the
whole process natively (access violation in `_ctypes.pyd`).

Fix: initialize every thread into the *multi*-threaded apartment (MTA) instead.
In a uniformly-MTA process, the audio endpoint objects (ThreadingModel=Both) can
be used and released from any thread, so a GC-triggered Release on another
thread is safe. `init_com_mta()` is called on the main thread at startup and at
the entry of every worker thread we spawn (even HID-only ones, because the GC
that frees a COM object can run on any thread that allocates).
"""
import sys
import threading

# Must precede `import comtypes`: selects the MTA apartment for comtypes' own
# per-thread COM machinery (see signal_companion/__init__.py for the full why).
sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED (MTA)

import comtypes

_com_init = threading.local()


def ensure_com_initialized():
    """Join this thread to the process MTA (idempotent per thread)."""
    if not getattr(_com_init, "done", False):
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:
            # Already initialized with a different model on this thread — fine.
            pass
        _com_init.done = True


# Back-compat alias; both names join the MTA.
init_com_mta = ensure_com_initialized
