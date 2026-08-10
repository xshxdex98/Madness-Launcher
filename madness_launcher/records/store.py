"""Your own lap records, kept between runs.

Separate from whatever the community board says. A player's own times should
be there the moment they finish a race — before the relay has picked anything
up, whether or not they submit at all, and whether or not they are online.
The shared board is an addition to this, not a replacement for it.

Only the best time per race, per difficulty, per board is kept: a leaderboard
of one person's every attempt is a log, not a record.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .. import paths
from ..news.model import safe_url
from . import mm1
from .session import Submission

# A guard against a file that has somehow grown unbounded, not a real limit:
# 32 races x 2 difficulties x 2 boards is 128 for Chicago.
MAX_RECORDS = 2000


def store_file() -> Path:
    return paths.app_root() / "records.json"


def _key(entry: Submission) -> tuple:
    return (entry.game, entry.board, entry.difficulty, entry.race)


def _from_dict(item: object) -> Submission | None:
    """One record out of stored or published JSON, or None if unreadable.

    Shared by the local file and the community feed, because the second comes
    off the network and has to be held to at least the standard of the first.
    """
    if not isinstance(item, dict):
        return None
    try:
        seconds = float(item.get("seconds", 0.0))
        race = int(item.get("race", -1))
    except (TypeError, ValueError):
        return None
    name = str(item.get("race_name", ""))
    if race < 0:
        # An external leaderboard knows the race by name only; the index is
        # this install's own numbering and is resolved here.
        race = mm1.race_index_by_name(name)
    if race < 0 or not (0 < seconds < 86400):
        return None
    car = str(item.get("car", ""))
    return Submission(
        game=str(item.get("game", ""))[:16],
        board=str(item.get("board", ""))[:16],
        race=race,
        # A published record names its own race, but an older relay may not
        # have. Falling back to this install's table beats showing a blank.
        race_name=(name or mm1.race_label(race))[:80],
        # External leaderboards do not classify a race; once it has been
        # placed by name, this install's own table knows what kind it is.
        race_kind=(str(item.get("race_kind", "")) or mm1.race_kind(race))[:16],
        difficulty=str(item.get("difficulty", ""))[:16],
        car=car[:40],
        # Published records carry the raw car id only; the pretty name is
        # derived here so the board reads the same as the local table.
        car_name=str(item.get("car_name") or mm1.pretty_car(car))[:60],
        seconds=seconds,
        driver=str(item.get("driver", ""))[:40],
        username=str(item.get("username", ""))[:40],
        set_at=str(item.get("set_at", ""))[:32],
        mods=[str(m)[:64] for m in (item.get("mods") or [])][:64],
        source=str(item.get("source", "launcher"))[:24],
        url=safe_url(item.get("url")),
    )


def load() -> list[Submission]:
    try:
        raw = json.loads(store_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    parsed = (_from_dict(i) for i in (raw.get("records") or [])[:MAX_RECORDS])
    return [r for r in parsed if r is not None]


def from_feed(published: list) -> list[Submission]:
    """Records the relay collected from the board channel."""
    parsed = (_from_dict(i) for i in (published or [])[:MAX_RECORDS])
    return [r for r in parsed if r is not None]


def save(records: list[Submission]) -> None:
    target = store_file()
    try:
        paths.ensure_dirs(target.parent)
        payload = json.dumps(
            {"version": 1, "records": [r.as_dict() for r in records[:MAX_RECORDS]]},
            indent=2,
        ).encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            os.replace(tmp, target)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        # Losing the local copy costs the tab its history, not the session.
        pass


def merge(existing: list[Submission], fresh: list[Submission]) -> list[Submission]:
    """Fold new records in, keeping only the best time for each slot."""
    best: dict[tuple, Submission] = {_key(r): r for r in existing}
    for entry in fresh:
        current = best.get(_key(entry))
        if current is None or entry.seconds < current.seconds:
            best[_key(entry)] = entry
    return sorted(
        best.values(), key=lambda r: (r.game, r.board, r.difficulty, r.race)
    )
