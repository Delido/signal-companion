"""Sound playback helper. Windows-first (winsound), with a graceful no-op
fallback so plugins never crash if audio is unavailable.

Plays asynchronously so callers (poller threads) aren't blocked."""
import logging
import os


def play_sound(path=None):
    """Play a WAV file asynchronously. If `path` is None / missing, falls back
    to the Windows default 'asterisk' system sound. Returns True if a play was
    initiated."""
    try:
        import winsound
    except ImportError:
        logging.warning("[audio] winsound unavailable on this platform")
        return False

    try:
        if path and os.path.isfile(path):
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            if path:
                logging.warning(f"[audio] sound file not found: {path}; using system default")
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return True
    except Exception:
        logging.exception("[audio] playback failed")
        return False
