"""Generate battery_low.wav — the default Battery Alert sound.

A short descending three-tone chime (G5 → E5 → C5), the classic "low battery"
motif. Pure stdlib (wave + struct + math); run to regenerate the .wav:

    python signal_companion/plugins/battery_alert/sounds/_generate.py
"""
import math
import struct
import wave
from pathlib import Path

RATE = 44100
AMPL = 0.45              # 0..1 headroom so it isn't harsh
TONES = [783.99, 659.25, 523.25]   # G5, E5, C5 (descending)
TONE_MS = 180
GAP_MS = 70
FADE_MS = 12            # fade in/out per tone to avoid clicks


def _tone(freq, ms):
    n = int(RATE * ms / 1000)
    fade = max(1, int(RATE * FADE_MS / 1000))
    for i in range(n):
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > n - fade:
            env = (n - i) / fade
        yield AMPL * env * math.sin(2 * math.pi * freq * i / RATE)


def _silence(ms):
    for _ in range(int(RATE * ms / 1000)):
        yield 0.0


def main():
    samples = []
    for t in TONES:
        samples.extend(_tone(t, TONE_MS))
        samples.extend(_silence(GAP_MS))

    out = Path(__file__).resolve().parent / "battery_low.wav"
    with wave.open(str(out), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)               # 16-bit
        w.setframerate(RATE)
        w.writeframes(b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples
        ))
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
