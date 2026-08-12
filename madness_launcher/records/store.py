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
from . import motocross, reader
from .session import Submission

# A guard against a file that has somehow grown unbounded, not a real limit:
# 32 races x 2 difficulties x 2 boards is 128 for Chicago.
MAX_RECORDS = 2000


def store_file() -> Path:
    return paths.app_root() / "records.json"


def _key(entry: Submission) -> tuple:
    """What counts as the same record.

    Includes who set it. Without that, merging the community feed with your
    own times keeps one row per race and everyone but the fastest disappears
    — which for a new player is every race they have ever driven.

    Includes the car, because the game records a time against the car it was
    driven in. Beating your own Mustang lap replaces that lap; the same race
    in a different car is a different record and stands on its own.

    Source is deliberately NOT part of it: one person has one best time per
    car on a race however it reached us, so beating your own published run
    replaces it rather than sitting beside it.
    """
    return (
        entry.game,
        entry.board,
        entry.city.lower(),
        entry.difficulty,
        entry.race,
        (entry.username or entry.driver).lower(),
        entry.car.lower(),
    )


def _from_dict(item: object) -> Submission | None:
    """One record out of stored or published JSON, or None if unreadable.

    Shared by the local file and the community feed, because the second comes
    off the network and has to be held to at least the standard of the first.
    """
    if not isinstance(item, dict):
        return None
    try:
        # Same three decimals the rest of the system uses, so a value that
        # has been through JSON compares equal to one straight off disk.
        seconds = round(float(item.get("seconds", 0.0)), 3)
        race = int(item.get("race", -1))
    except (TypeError, ValueError):
        return None
    name = str(item.get("race_name", ""))
    # Every lookup below is per game and per city. Resolving a name without
    # them searched Midtown Madness's table for a San Francisco race and
    # dropped the record, which is how a whole game's world records would
    # have gone missing in silence.
    game = str(item.get("game", ""))[:16]
    city = str(item.get("city", ""))[:24]
    if race < 0:
        # An external leaderboard knows the race by name only; the index is
        # this install's own numbering and is resolved here.
        race = reader.race_index_by_name(name, game, city)
    if race < 0 or not (0 < seconds < 86400):
        return None
    car = str(item.get("car", ""))
    track = str(item.get("track", ""))[:64]
    if track:
        # Motocross names are learned rather than looked up, so a record
        # stored or published before its track had a name still carries the
        # filename. The name is re-derived on the way in instead of being
        # taken as written, which is what makes a name learned today fix
        # every row that was saved yesterday.
        learned = motocross.pretty_track(track)
        if learned:
            name = learned
    return Submission(
        game=game,
        board=str(item.get("board", ""))[:16],
        city=city,
        race=race,
        # A published record names its own race, but an older relay may not
        # have. Falling back to this install's table beats showing a blank.
        race_name=(name or reader.race_label(race, game, city))[:80],
        # External leaderboards do not classify a race; once it has been
        # placed by name, this install's own table knows what kind it is.
        race_kind=(str(item.get("race_kind", ""))
                   or reader.race_kind(race, game, city))[:16],
        difficulty=str(item.get("difficulty", ""))[:16],
        car=car[:40],
        # Published records carry the raw car id only; the pretty name is
        # derived here so the board reads the same as the local table.
        car_name=str(item.get("car_name") or reader.pretty_car(car))[:60],
        seconds=seconds,
        driver=str(item.get("driver", ""))[:40],
        username=str(item.get("username", ""))[:40],
        set_at=str(item.get("set_at", ""))[:32],
        mods=[str(m)[:64] for m in (item.get("mods") or [])][:64],
        source=str(item.get("source", "launcher"))[:24],
        url=safe_url(item.get("url")),
        track=track,
    )


def key_id(entry: Submission) -> str:
    """What the forgotten list remembers a record by.

    Deliberately NOT the full identity. That one has grown twice during this
    feature — the car was added, then the city — and each time every stored
    key stopped matching, so records the user had deleted quietly came back
    on the next launch.

    This is the part that describes the race rather than the claimant: game,
    board, city, difficulty, race and car. It leaves out who set it, so a
    rename or a change to how drivers are identified cannot resurrect a
    deleted record. Blunter than the identity, and that is the point.
    """
    return "|".join(str(part) for part in (
        entry.game,
        entry.board,
        entry.city.lower(),
        entry.difficulty,
        entry.race,
        entry.car.lower(),
    ))


def forgotten() -> set[str]:
    """Records the user has removed and does not want back.

    The game's own tables are re-read at every launch, so deleting a row from
    the store alone achieves nothing: the next start finds it on disk again,
    treats it as new, and publishes it. Remembering the removal is the only
    thing that makes it stick.
    """
    try:
        raw = json.loads(store_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    listed = raw.get("forgotten")
    return {str(k) for k in listed} if isinstance(listed, list) else set()


def forget(entries: list[Submission]) -> None:
    """Remove records and stop them coming back."""
    dropped = {key_id(e) for e in entries}
    kept = [r for r in load() if key_id(r) not in dropped]
    save(kept, forgotten() | dropped)


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


def save(records: list[Submission], forget_keys: set[str] | None = None) -> None:
    target = store_file()
    if forget_keys is None:
        forget_keys = forgotten()
    try:
        paths.ensure_dirs(target.parent)
        payload = json.dumps(
            {
                "version": 1,
                "records": [r.as_dict() for r in records[:MAX_RECORDS]],
                "forgotten": sorted(forget_keys)[:MAX_RECORDS],
            },
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
        if current is None or entry.seconds < current.seconds - 5e-4:
            best[_key(entry)] = entry
    return sorted(
        best.values(), key=lambda r: (r.game, r.board, r.difficulty, r.race)
    )
