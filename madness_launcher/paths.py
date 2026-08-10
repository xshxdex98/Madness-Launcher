"""Filesystem locations owned by the launcher.

Everything the launcher writes lives under one root so it can be backed up or
removed in a single step. Nothing is written into a game folder except by the
mod manager, which keeps receipts (see mods.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource(*parts: str) -> Path:
    """A file shipped with the launcher, not written by it.

    PyInstaller unpacks the bundle to a temporary folder and points
    ``sys._MEIPASS`` at it, so a path relative to the source tree is wrong in a
    frozen build. Running from source, the project root is two levels up from
    this module.
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root.joinpath(*parts)


def app_root() -> Path:
    """Root of the launcher's own data. Honours MADNESS_LAUNCHER_HOME for tests."""
    override = os.environ.get("MADNESS_LAUNCHER_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "MadnessLauncher"


def config_file() -> Path:
    return app_root() / "config.json"


def mod_library(game_id: str) -> Path:
    """Where imported (but not necessarily enabled) mods are stored."""
    return app_root() / "mods" / game_id


def backup_dir(game_id: str) -> Path:
    """Original game files displaced by a mod are parked here."""
    return app_root() / "backups" / game_id


def log_dir() -> Path:
    return app_root() / "logs"


def ensure_dirs(*dirs: Path) -> None:
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
