"""PyInstaller entry point for SignalCompanion.

Thin launcher so the frozen exe (and the --settings subprocess it spawns) run
through the package's app.main(). Kept at the repo root so `signal_companion`
is importable as a top-level package during the build.
"""
from signal_companion.app import main

if __name__ == "__main__":
    main()
