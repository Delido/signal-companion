"""Serve ANIMATED fake CS2 state over the same HTTPS bridge the app uses, so the
effect can be tested without a live match. Cycles through obvious phases every
~3 s: full HP (green) -> low HP (red pulse) -> bomb planted (red blink) ->
flashbang (white) -> dead (dim team). Stop the real app first (it owns :3443).

    python dev_probes/fake_cs2_feed.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_companion.core import config as config_mod
from signal_companion.plugins.cs2_gsi import tls_bridge

_start = time.time()
PHASE_SECONDS = 3
PHASES = ["full_hp", "low_hp", "bomb", "flash", "dead"]


def fake_state():
    t = time.time() - _start
    phase = PHASES[int(t / PHASE_SECONDS) % len(PHASES)]
    team = "T" if int(t / (PHASE_SECONDS * len(PHASES))) % 2 == 0 else "CT"
    s = {"connected": True, "ts": time.time(), "team": team, "activity": "playing",
         "round_phase": "live", "health": 100, "armor": 100, "flashed": 0,
         "smoked": 0, "burning": 0, "bomb": None, "round_kills": 0,
         "phase": phase}
    if phase == "full_hp":
        s["health"] = 100
    elif phase == "low_hp":
        s["health"] = 15
    elif phase == "bomb":
        s["bomb"] = "planted"
    elif phase == "flash":
        s["flashed"] = 255
    elif phase == "dead":
        s["health"] = 0
    return s


def main():
    info = tls_bridge.ensure_certs(config_mod.CONFIG_DIR / "certs")
    tls_bridge.patch_cacert(info["ca_pem"])
    srv = tls_bridge.HttpsStateServer("127.0.0.1", 3443, info["chain"], info["key"], fake_state)
    srv.start()
    print("FAKE CS2 feed on https://127.0.0.1:3443/state")
    print("Cycles: full HP (green) -> low HP (red pulse) -> bomb (red blink) -> flash (white) -> dead")
    try:
        while True:
            time.sleep(2)
            print("  phase:", fake_state()["phase"], "hp:", fake_state()["health"])
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
