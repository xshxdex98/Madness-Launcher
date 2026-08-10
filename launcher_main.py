"""Entry point for the standalone build.

Deliberately separate from `madness_launcher/__main__.py`. That file uses a
relative import (`from .app import main`), which is correct for
`python -m madness_launcher` but fails under PyInstaller: the entry script runs
as a top-level module with no parent package, so the relative import raises
ImportError before anything is on screen. With a windowed build there is no
console to show it, so the application simply appears not to start.

This module imports absolutely, which works both ways.
"""

from madness_launcher.app import main

if __name__ == "__main__":
    raise SystemExit(main())
