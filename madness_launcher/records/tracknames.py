"""Real names for Motocross Madness 2 tracks, once anybody has learned one.

The names are not readable from the game — the .env files are encrypted and
LANG.DLL holds only the descriptions — so a track goes by its filename until
a launcher watches somebody ride it and reads the name out of the rider
profile. That costs one race per track and it should only cost it once, for
one person: a name learned here is attached to every record published from
this machine, and the relay hands it to everyone else.

Written the same way the config is, atomically, for the same reason: a
half-written map is worse than none.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import paths
from . import motocross

# Names are short. This is a guard against a file that has somehow grown
# unbounded rather than a real limit; the game has a few hundred tracks at
# the outside.
MAX_NAMES = 5000
MAX_LENGTH = 80


def store_file() -> Path:
    return paths.app_root() / "mcm2_tracks.json"


def load() -> dict[str, str]:
    """The learned names, and install them into the reader.

    Never raises: a corrupt map costs nice track names, not a startup.
    """
    names: dict[str, str] = {}
    try:
        raw = json.loads(store_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if isinstance(raw, dict):
        for stem, name in list(raw.items())[:MAX_NAMES]:
            if isinstance(stem, str) and isinstance(name, str) and name.strip():
                names[stem.lower()] = name.strip()[:MAX_LENGTH]
    motocross.set_learned(names)
    return names


def save(names: dict[str, str]) -> None:
    paths.ensure_dirs(paths.app_root())
    target = store_file()
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(names.items())), fh, indent=2)
        os.replace(tmp, target)
    except OSError:
        Path(tmp).unlink(missing_ok=True)


def remember(stem: str, name: str) -> bool:
    """Learn one track's name. True if it was new.

    A name already known is not overwritten. The first launcher to see a
    track names it, and a later reading that disagrees is more likely to be
    a mispairing than a correction — the pairing gives up whenever it is
    unsure, so the ones that get through are the confident ones.
    """
    stem, name = str(stem).strip().lower(), str(name).strip()[:MAX_LENGTH]
    if not stem or not name:
        return False
    known = motocross.learned_names()
    if known.get(stem):
        return False
    known[stem] = name
    motocross.set_learned(known)
    save(known)
    return True


def adopt(names: dict[str, str]) -> int:
    """Take in names carried by the community feed. Returns how many were new.

    A record published by somebody else names its own track, which is how a
    name learned on one machine reaches the rest without anybody having to
    ride anything.
    """
    known = motocross.learned_names()
    added = 0
    for stem, name in (names or {}).items():
        stem, name = str(stem).strip().lower(), str(name).strip()[:MAX_LENGTH]
        if stem and name and not known.get(stem):
            known[stem] = name
            added += 1
    if added:
        motocross.set_learned(known)
        save(known)
    return added
