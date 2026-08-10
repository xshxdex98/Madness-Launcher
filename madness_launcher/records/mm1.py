"""Reading Midtown Madness's own best-time tables.

The game already keeps what a leaderboard needs. Each city folder under
`players/` holds one file per difficulty — `players/chicago/amateur.dat`,
`pro.dat` — and every entry in them carries the driver's name, the car they
used and the time, which is exactly the three things a record consists of.

That makes this a file-reading problem rather than a memory-reading one: no
injection, no hooking the game loop, nothing that breaks when the executable
is patched. The launcher takes a snapshot when it starts the game and another
when the process exits, and whatever improved in between is a new record.

Format, established by inspecting real files (see tools/mm1_probe.py, which
is how the layout below was confirmed and how it can be re-confirmed if a mod
turns out to write something different):

    offset  size  meaning
    0       4     magic, 1234
    4       4     12
    8       ...   360 records of 132 bytes
    ...     8     trailing zeros

    record layout
    0       4     hash or checksum, not needed for reading
    4       40    driver name, NUL-terminated
    44      80    car name, NUL-terminated ("vpmustang99")
    124     4     time in seconds, float32
    128     4     non-zero when the slot holds anything at all

Records group in tens: slots 0-9 belong to the first race, 10-19 to the
second, and so on. Which race that actually *is* has to be established by
experiment rather than assumed — see RACE_NAMES.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = 1234
HEADER = 8
RECORD = 132
SLOTS_PER_RACE = 10

# Offsets within one record.
_DRIVER = slice(4, 44)
_CAR = slice(44, 124)
_TIME = slice(124, 128)
_VALID = slice(128, 132)

# Within a race's ten slots the entries alternate: an even sub-slot holds a
# time somebody drove, and the odd one after it holds the game's own par time
# for that entry. It shows in the data without ambiguity — every odd sub-slot
# across both difficulty files is a round multiple of 25 seconds (7:30, 12:30,
# 3:20) and every even one is not (41.320, 1:17.318). Publishing the odd ones
# would fill the board with times nobody set.
PAR_SLOTS_ARE_ODD = True

# Some slots carry a set flag with a time of 0.0 and no car at all — nothing
# was ever driven there, and a 0.000 would sit unbeatable at the top of every
# board.
MIN_TIME = 0.5
MAX_TIME = 3600.0

# Which race each group of ten slots belongs to. Deliberately empty: the
# mapping cannot be read out of the file, and guessing it would put real times
# under the wrong race name, which is worse than showing no name at all.
# tools/mm1_probe.py resolves it one race at a time by diffing.
RACE_NAMES: dict[int, str] = {}

# The game's internal car names are lowercase and prefixed; these are what a
# person calls them. Unknown cars fall back to the raw name with the prefix
# stripped, so a modded car still reads sensibly.
CAR_NAMES = {
    "vpbug": "VW Beetle",
    "vpbullet": "Bullet",
    "vpbus": "City Bus",
    "vpcaddie": "Cadillac Eldorado",
    "vpcop": "Police Cruiser",
    "vpford": "Ford F-350",
    "vpmustang99": "Ford Mustang GT",
    "vppanoz": "Panoz Roadster",
    "vppanozgt": "Panoz GTR-1",
    "vpsemi": "Freightliner Semi",
}

# The stock roster, read out of the game's own ui.ar rather than recalled from
# a 1999 manual: exactly these ten car ids appear there, and none of the
# add-on vehicles that ship beside it (vpdisco, vpredcar, vpeb184) do. A car
# outside this set is a custom one, and neither board accepts those yet.
VANILLA_CARS = frozenset(CAR_NAMES)

# Which board a run belongs on.
BOARD_VANILLA = "vanilla"
BOARD_MODDED = "modded"


def is_vanilla_car(car: str) -> bool:
    return car.lower() in VANILLA_CARS


def classify(car: str, enabled_mods: list[str] | tuple[str, ...]) -> str | None:
    """Which board a time belongs on, or None if it belongs on neither.

    Vanilla means the game as shipped: stock car, stock races, nothing loaded
    that could alter handling. Modded allows racepacks — different tracks, but
    still a stock car, so the times remain about driving rather than about
    which vehicle someone downloaded.

    The vanilla test is deliberately stricter than "no handling mods": any
    enabled archive at all disqualifies a run. Telling a graphics pack from a
    handling pack means reading the contents of an ARES archive, and until
    that exists the failure has to be chosen. Being too strict misfiles a
    legitimate vanilla run onto the modded board, which is a shrug. Being too
    lenient lets a modified-handling run set the vanilla record, which poisons
    the board permanently and cannot be detected after the fact.
    """
    if not is_vanilla_car(car):
        return None
    return BOARD_MODDED if enabled_mods else BOARD_VANILLA


def pretty_car(raw: str) -> str:
    """A car name fit to show someone."""
    known = CAR_NAMES.get(raw.lower())
    if known:
        return known
    trimmed = raw[2:] if raw.lower().startswith("vp") else raw
    return trimmed.replace("_", " ").strip().title() or raw


def race_label(index: int) -> str:
    """What to call race `index` — its name once known, its number until then."""
    return RACE_NAMES.get(index) or f"Race {index + 1}"


@dataclass(frozen=True)
class LapRecord:
    """One time out of the game's own table."""

    slot: int
    driver: str
    car: str
    seconds: float
    city: str = ""
    difficulty: str = ""

    @property
    def race(self) -> int:
        return self.slot // SLOTS_PER_RACE

    @property
    def race_name(self) -> str:
        return race_label(self.race)

    @property
    def car_name(self) -> str:
        return pretty_car(self.car)

    @property
    def formatted(self) -> str:
        """m:ss.mmm, the way a lap time is written."""
        minutes, seconds = divmod(self.seconds, 60)
        if minutes:
            return f"{int(minutes)}:{seconds:06.3f}"
        return f"{seconds:.3f}"

    def key(self) -> tuple[str, str, int]:
        """Identifies the slot this record occupies, ignoring the time in it."""
        return (self.city, self.difficulty, self.slot)


def _string(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("latin-1", "replace").strip()


def parse(path: Path, city: str = "", difficulty: str = "") -> list[LapRecord]:
    """Every usable record in one .dat file.

    Never raises on a bad file: a profile the launcher cannot read is a
    leaderboard with one fewer entry, not a crash on the way out of a game.
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return []
    if len(blob) < HEADER + RECORD:
        return []
    magic, _ = struct.unpack_from("<II", blob, 0)
    if magic != MAGIC:
        return []

    city = city or path.parent.name
    difficulty = difficulty or path.stem
    out: list[LapRecord] = []
    for slot in range((len(blob) - HEADER) // RECORD):
        start = HEADER + slot * RECORD
        chunk = blob[start : start + RECORD]
        if not struct.unpack("<I", chunk[_VALID])[0]:
            continue
        # The game's par time for the entry before it, not a lap anyone drove.
        if PAR_SLOTS_ARE_ODD and slot % 2:
            continue
        seconds = struct.unpack("<f", chunk[_TIME])[0]
        car = _string(chunk[_CAR])
        # An entry with no car never had anyone drive it, whatever the flag says.
        if not car or not (MIN_TIME <= seconds <= MAX_TIME):
            continue
        out.append(
            LapRecord(
                slot=slot,
                driver=_string(chunk[_DRIVER]) or "Unknown",
                car=car,
                seconds=seconds,
                city=city,
                difficulty=difficulty,
            )
        )
    return out


def player_root(install: Path) -> Path:
    return Path(install) / "players"


def record_files(install: Path) -> list[Path]:
    """Every per-city, per-difficulty table in an install."""
    root = player_root(install)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*.dat") if p.is_file())


def snapshot(install: Path) -> dict[tuple[str, str, int], LapRecord]:
    """Every record in an install, keyed by the slot it sits in."""
    found: dict[tuple[str, str, int], LapRecord] = {}
    for path in record_files(install):
        for record in parse(path):
            found[record.key()] = record
    return found


def improvements(
    before: dict[tuple[str, str, int], LapRecord],
    after: dict[tuple[str, str, int], LapRecord],
) -> list[LapRecord]:
    """Records that are new, or faster than they were.

    Comparing snapshots rather than trusting the file wholesale is what keeps
    a session from re-reporting every time already in the table as though it
    had just been driven.
    """
    out: list[LapRecord] = []
    for key, record in after.items():
        previous = before.get(key)
        if previous is None or record.seconds < previous.seconds - 1e-4:
            out.append(record)
    out.sort(key=lambda r: (r.city, r.difficulty, r.slot))
    return out
