"""SignalCompanion — extensible tray companion for SignalRGB.

Fills the gaps SignalRGB's plugin sandbox leaves open (network, processes,
Windows audio, direct HID) via a drop-in plugin system. See core/plugin.py
for the plugin contract and plugins/ for the bundled plugins.
"""

# comtypes reads sys.coinit_flags AT IMPORT TIME to choose its COM apartment and
# wire up its per-thread init/CoUninitialize machinery. Its default is STA (2),
# which tears apartments down on thread exit and makes a COM object freed by the
# GC on another thread crash natively (access violation in comtypes' Release —
# captured in fault.log). Forcing MTA (0) here, before ANY comtypes import in the
# package, makes the whole process uniformly multi-threaded so cross-thread
# Release is safe. MUST stay above everything else.
import sys as _sys
_sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED (MTA)

__version__ = "2.2.1"
