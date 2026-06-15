"""Process-wide COM handling for SignalCompanion.

pycaw/comtypes wrap COM objects whose `Release()` runs from `__del__`. Two hard
lessons, both diagnosed from native crash dumps (fault.log, access violation in
comtypes' `Release`):

1. **Apartment.** comtypes picks its COM apartment from `sys.coinit_flags` at
   import time (default STA). STA tears apartments down on thread exit, so a COM
   object freed on another thread crashes. We force MTA (`coinit_flags = 0`)
   before importing comtypes.

2. **Finalization thread.** Even uniformly-MTA, finalizing a comtypes object on a
   thread *other than the one that created it* crashes (empirically: a single
   thread that creates+uses+releases is safe; a cross-thread GC finalize is not).
   Python's cyclic GC fires on whatever thread happens to allocate — including
   pywinusb's internal HID read threads — and finalizing a stray COM object there
   killed the process.

   Fix: route ALL comtypes work (audio + microphone) through ONE dedicated COM
   worker thread via `com_submit`, and run the cyclic GC ONLY on that same thread
   (automatic GC is disabled process-wide). Then every COM object is created,
   used and finalized on the one thread — never cross-thread.
"""
import gc
import queue
import sys
import threading

# Must precede `import comtypes`: selects the MTA apartment for comtypes' own
# per-thread COM machinery (see point 1 above).
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


# ── single COM worker thread (the only place comtypes objects live) ──
class _ComWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="COMWorker")
        self._q = queue.Queue()

    def run(self):
        ensure_com_initialized()
        while True:
            try:
                fn, box, done = self._q.get(timeout=2.0)
            except queue.Empty:
                gc.collect()          # collect on the COM-owning thread when idle
                continue
            try:
                box["value"] = fn()
            except Exception as e:    # propagated to the caller of submit()
                box["exc"] = e
            finally:
                done.set()
                # Finalize this job's cyclic comtypes garbage here, on the thread
                # that created it — the only place it's safe to do so.
                gc.collect()

    def submit(self, fn, timeout=15.0):
        box = {}
        done = threading.Event()
        self._q.put((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError("COM worker timed out")
        if "exc" in box:
            raise box["exc"]
        return box.get("value")


_com_worker = None
_com_worker_lock = threading.Lock()


def start_com_worker():
    """Start the single COM worker and disable automatic GC so cyclic comtypes
    finalization happens ONLY on that thread. Idempotent. Call once from the tray
    process at startup (the short-lived settings process doesn't need it)."""
    global _com_worker
    with _com_worker_lock:
        if _com_worker is None:
            gc.disable()
            _com_worker = _ComWorker()
            _com_worker.start()
    return _com_worker


def com_submit(fn):
    """Run fn() on the dedicated COM worker thread and return its result.

    Falls back to running inline if the worker isn't started (e.g. the settings
    process), which is safe there because that process is single-threaded."""
    if _com_worker is None:
        return fn()
    return _com_worker.submit(fn)
