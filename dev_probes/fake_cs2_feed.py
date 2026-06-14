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
# (name, seconds) — bomb held long enough to hear the tick accelerate; flash
# fades; dead long enough to see the vignette close then respawn.
SEGMENTS = [("full_hp", 3), ("low_hp", 3), ("bomb", 8), ("explode", 2), ("flash", 3), ("dead", 5), ("over", 3)]
TOTAL = sum(s for _, s in SEGMENTS)


def fake_state():
    t = (time.time() - _start) % TOTAL
    loop = int((time.time() - _start) / TOTAL)
    acc = 0.0
    phase, seg_t, seg_len = "full_hp", 0.0, 1.0
    for name, length in SEGMENTS:
        if t < acc + length:
            phase, seg_t, seg_len = name, t - acc, length
            break
        acc += length
    team = "CT" if loop % 2 == 0 else "T"
    other = "T" if team == "CT" else "CT"
    s = {"connected": True, "ts": time.time(), "team": team, "activity": "playing",
         "round_phase": "live", "health": 100, "armor": 100, "flashed": 0,
         "smoked": 0, "burning": 0, "bomb": None, "round_kills": 0,
         "win_team": None, "phase": phase}
    if phase == "low_hp":
        s["health"] = 15
    elif phase == "bomb":
        s["bomb"] = "planted"
    elif phase == "explode":                    # alternate explosion / defuse
        s["bomb"] = "exploded" if loop % 2 == 0 else "defused"
        s["phase"] = "explode" if loop % 2 == 0 else "defuse"
    elif phase == "flash":
        s["flashed"] = int(255 * max(0.0, 1.0 - seg_t / seg_len))  # fade out
    elif phase == "dead":
        s["health"] = 0
    elif phase == "over":                       # alternate win / loss each loop
        s["round_phase"] = "over"
        s["win_team"] = team if loop % 2 == 0 else other
        s["phase"] = "win" if loop % 2 == 0 else "loss"
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
