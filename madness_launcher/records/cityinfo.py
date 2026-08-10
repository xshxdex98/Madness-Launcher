"""The race and car tables, read out of the game's own archives.

Midtown Madness ships its city definition as a plain `key=value` block inside
`ui.ar`, and it is exactly the thing a leaderboard needs:

    BlitzCount=10
    CircuitCount=10
    CheckpointCount=12
    BlitzNames=Dearborn Dash|River Wild & Wacker|Under the El|...
    CircuitNames=The Littler Loop|Riverside Run|...
    CheckpointNames=Beginner's Luck|Tough Turns & a Tunnel|...

That block is read here rather than copied into the source, for two reasons.
A hardcoded list is a list that goes stale, and more importantly a racepack
overrides the table with its own — so the only way to know what race a slot
actually refers to on *this* install is to ask the archives on it.

The block is found by scanning the archive's bytes for the keys. The ARES
container is not parsed: the strings are stored uncompressed and a scan finds
them in a few milliseconds, where a full archive reader would be several
hundred lines of format handling for no additional information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The order these appear in is the order the game numbers its races, and the
# order the record slots follow: Blitz first, then Circuit, then Checkpoint.
RACE_GROUPS = ("Blitz", "Circuit", "Checkpoint")

# Archives are scanned newest-priority-first. A racepack loads over the base
# game by leading '!' in its filename, and its table wins the same way.
_BASE_ARCHIVES = ("ui.ar", "core.ar")

_MAX_SCAN_BYTES = 64 * 1024 * 1024


def _field(blob: bytes, key: str) -> str:
    match = re.search(
        rb"\b" + re.escape(key.encode()) + rb"=([^\x00\r\n]{1,4000})", blob
    )
    return match.group(1).decode("latin-1", "replace").strip() if match else ""


@dataclass(frozen=True)
class Race:
    index: int
    name: str
    # "Blitz", "Circuit" or "Checkpoint" — worth showing, since a 40-second
    # Blitz and a four-minute Circuit are not comparable achievements.
    kind: str


@dataclass(frozen=True)
class Car:
    id: str
    name: str


@dataclass(frozen=True)
class CityInfo:
    city: str = ""
    races: tuple[Race, ...] = ()
    cars: tuple[Car, ...] = ()
    # Which archive the race table came from. Shown in the UI so that "why
    # does it say Museum Marathon when I raced something else" has an answer.
    source: str = ""

    def race(self, index: int) -> Race | None:
        return self.races[index] if 0 <= index < len(self.races) else None

    def car_names(self) -> dict[str, str]:
        return {c.id: c.name for c in self.cars}


def _parse(blob: bytes, source: str) -> CityInfo | None:
    names: list[Race] = []
    for kind in RACE_GROUPS:
        raw = _field(blob, f"{kind}Names")
        if not raw:
            continue
        for name in raw.split("|"):
            name = name.strip()
            if name:
                names.append(Race(len(names), name, kind))
    if not names:
        return None

    cars = [
        Car(bn.decode("latin-1"), desc.decode("latin-1", "replace").strip())
        for bn, desc in re.findall(
            rb"BaseName=(\w{1,40})[\x00\s]+Description=([^\x00\r\n]{1,60})", blob
        )
    ]
    # The same car can be declared more than once across an archive; the first
    # declaration is the one the game uses.
    seen: set[str] = set()
    unique = [c for c in cars if not (c.id.lower() in seen or seen.add(c.id.lower()))]

    return CityInfo(
        city=_field(blob, "LocalizedName") or _field(blob, "MapName"),
        races=tuple(names),
        cars=tuple(unique),
        source=source,
    )


def _archives(install: Path) -> list[Path]:
    """Base archives first; a caller wanting the modded table adds racepacks."""
    root = Path(install)
    found = [root / name for name in _BASE_ARCHIVES]
    return [p for p in found if p.is_file()]


# The stock Chicago race list, in the order the game numbers it. Read out of
# a retail ui.ar rather than typed from memory, and kept only as a fallback:
# an install's own archives are always preferred, because a racepack replaces
# this table and only that install knows what it replaced it with.
#
# Needed because the board has to work before anyone has configured the game.
# Without it a launcher with no Midtown Madness install cannot place a record
# that names its race, and silently shows an empty leaderboard.
_STOCK = (
    ("Blitz", (
        "Dearborn Dash", "River Wild & Wacker", "Under the El",
        "Double-Back Blitz", "Grant Park Parade", "Wild Blue Blitz",
        "Navy Pier Peel-Out", "Bear Cub Blitz", "Race for a Space",
        "Tall Tower Blitz",
    )),
    ("Circuit", (
        "The Littler Loop", "Riverside Run", "Tunnel Turner",
        "Downtown Driver", "Museum Marathon", "South End Circuit",
        "City Central", "North End Navigator", "Old Town Twist",
        "Loop-De-Loop",
    )),
    ("Checkpoint", (
        "Beginner's Luck", "Tough Turns & a Tunnel", "North River Run",
        "Soldier Sneaker", "Freeway Flyer", "Nocturnal Navigator",
        "Beat the Bridges", "Crosstown Switchback", "Perimeter Perils",
        "Aptitude Test", "Beetle Blast-a-Thon", "Frosty Finale",
    )),
)


def stock() -> CityInfo:
    """The retail Chicago tables, for when no install can be read."""
    races: list[Race] = []
    for kind, names in _STOCK:
        for name in names:
            races.append(Race(len(races), name, kind))
    return CityInfo(city="Chicago", races=tuple(races), source="built-in")


def read(install: Path) -> CityInfo | None:
    """The stock race and car tables for an install.

    Only the base archives are consulted, so this is the *vanilla* table even
    on an install with twenty racepacks sitting beside it. That is what the
    vanilla board has to be judged against.
    """
    for path in _archives(install):
        try:
            if path.stat().st_size > _MAX_SCAN_BYTES:
                continue
            blob = path.read_bytes()
        except OSError:
            continue
        info = _parse(blob, path.name)
        if info is not None:
            return info
    return None
