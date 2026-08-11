"""Reading a Madness game's own best-time tables.

Serves both Midtown Madness and Midtown Madness 2. Everything that
differs between them — header size, magic, cities, car roster, race
table, archive rule — lives in profiles.py, and every function here
takes a game id defaulting to mm1.

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
second, and so on, in the order the game lists them — Blitz, then Circuit,
then Checkpoint. Those names come from the install's own archives rather than
from a table here; see cityinfo.py.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from . import cityinfo, profiles

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

# Which race each group of ten slots belongs to. Filled from the install's own
# archives by `apply_city`, because the game states it outright — see
# cityinfo.py. Empty until then, and a race with no name shows as its number
# rather than as a guess.
RACE_NAMES: dict[int, str] = {}
RACE_KINDS: dict[int, str] = {}


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
# outside this set is a downloaded one, which makes the run modded rather
# than disqualifying it.
VANILLA_CARS = frozenset(CAR_NAMES)

# Which board a run belongs on.
BOARD_VANILLA = "vanilla"
BOARD_MODDED = "modded"


def apply_city(info: "cityinfo.CityInfo | None") -> None:
    """Adopt the race and car tables read from an install."""
    RACE_NAMES.clear()
    RACE_KINDS.clear()
    if info is None:
        return
    for race in info.races:
        RACE_NAMES[race.index] = race.name
        RACE_KINDS[race.index] = race.kind
    # The game's own descriptions beat the hand-written table below.
    CAR_NAMES.update(info.car_names())


def load_city(install: "Path | None" = None) -> "cityinfo.CityInfo":
    """Adopt the race and car tables, from an install if there is one.

    Falls back to the retail tables rather than to nothing. Records from the
    community and from speedrun.com name their race instead of numbering it,
    so with no table loaded every one of them fails to place and the board
    goes quietly empty — which is exactly what happened before this existed.
    """
    info = cityinfo.read(Path(install)) if install else None
    if info is None:
        info = cityinfo.stock()
    apply_city(info)
    return info


# Archives the game ships with. Everything else in the folder is something
# somebody added.
BASE_ARCHIVES = frozenset({"core.ar", "audio.ar", "ui.ar", "1560.ar"})

# The only added archives a vanilla run may have loaded, by content hash.
# Named by hash and not by filename because the filename carries no weight:
# load order is set by leading '!' so the same mod appears under many names,
# and renaming a handling mod to "wsfix16to9.ar" would otherwise be all it
# took to put a modified car on the vanilla board.
#
# These four change how the game is controlled or displayed, not how it
# drives — a widescreen fix, two mouse/keyboard fixes, and a patch that
# restores the stock handling rather than altering it.
VANILLA_ARCHIVES = {
    "6e369662d58cabaa5823698926b5af9c37e8c16536e8c140fb917adeeee0a911":
        "VanillaHLFix",
    "0d705e111e104884cece44e95f39bf74cd272c7fbe02640ab280e60465799f4c":
        "kbmousepad",
    "415dc193a5e4748ea4a1cda34394111fdd530f981890f1f35170587c15d355d1":
        "wsfix16to9",
    "3383ab0b7e38df92e9ec856726b80c39e6ff2d5581748afaefc06141e906942e":
        "mousemod",
}

# Sizes of the allowlisted files. An archive whose size matches none of them
# cannot be one of them, so it never has to be read — which keeps the check
# instant on a folder full of hundred-megabyte racepacks.
_ALLOWED_SIZES = {89_264, 673_184, 3_671_808, 26_016}

_HASH_CHUNK = 1 << 20


def archive_digest(path: Path) -> str:
    """SHA-256 of a file, or empty if it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(_HASH_CHUNK):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def active_archives(install: Path, game: str = "mm1") -> list[Path]:
    """Added .ar files the game will actually load.

    Only the game's own directory counts. Mods parked in subfolders — a
    staging area full of racepacks, say — are not loaded until they are
    copied up here, so a folder of them does not make a run modded.
    """
    spec = profiles.profile(game)
    root = Path(install)
    try:
        found = [p for p in root.glob("*.ar") if p.is_file()]
    except OSError:
        return []
    return sorted(
        p for p in found
        if p.name.lower() not in spec.base_archives
        and not (spec.stock_prefix
                 and p.name.lower().startswith(spec.stock_prefix))
    )


def unapproved_archives(install: Path, game: str = "mm1") -> list[str]:
    """Loaded archives that are not on the vanilla allowlist, by name.

    Read from the game folder rather than from the launcher's own list of
    enabled mods, because an archive dropped in by hand loads exactly the
    same way and the mod manager knows nothing about it.
    """
    spec = profiles.profile(game)
    out: list[str] = []
    for path in active_archives(install, game):
        try:
            size = path.stat().st_size
        except OSError:
            out.append(path.name)
            continue
        if (spec.vanilla_archives
                and size in _ALLOWED_SIZES
                and archive_digest(path) in spec.vanilla_archives):
            continue
        out.append(path.name)
    return out


def is_vanilla_car(car: str, game: str = "mm1") -> bool:
    return car.lower() in profiles.profile(game).vanilla_cars


def classify(car: str, unapproved: list[str] | tuple[str, ...],
             game: str = "mm1") -> str | None:
    """Which board a time belongs on, or None if it belongs on neither.

    Vanilla means the game as shipped, plus a short allowlist of fixes that
    change how it is controlled or displayed rather than how it drives.
    Modded allows anything else loaded — racepacks, new cities — but still
    requires a stock car, so the times stay about driving rather than about
    which vehicle somebody downloaded.

    `unapproved` is what unapproved_archives() found. Judging on identity
    rather than on a count means a widescreen fix no longer costs someone the
    vanilla board, while a renamed handling mod still does.

    A downloaded car is a modded run rather than no run at all. Dropping
    those outright threw away most of a player's history on an install with
    addon cars, and a time driven in one is still a time — it simply is not a
    vanilla one. Nothing returns None any more; the return type keeps the
    Optional so callers written against the old behaviour stay correct.
    """
    if not is_vanilla_car(car, game) or unapproved:
        return BOARD_MODDED
    return BOARD_VANILLA


def pretty_car(raw: str) -> str:
    """A car name fit to show someone."""
    known = CAR_NAMES.get(raw.lower())
    if known:
        return known
    trimmed = raw[2:] if raw.lower().startswith("vp") else raw
    return trimmed.replace("_", " ").strip().title() or raw


def _table(game: str, city: str) -> tuple[tuple[str, str], ...]:
    """A game's race list for a city, when it ships one here.

    MM1 reads its table out of whichever install is configured, so it
    has none here and falls through to RACE_NAMES. MM2 keeps its order
    in a compressed archive that could not be read, so its table was
    established by probing and lives in mm2tables.
    """
    spec = profiles.profile(game)
    if not spec.races:
        return ()
    wanted = (city or (spec.cities[0] if spec.cities else "")).lower()
    return spec.race_table(wanted)


def race_label(index: int, game: str = "mm1", city: str = "") -> str:
    """What to call race `index` — its name once known, its number until then."""
    table = _table(game, city)
    if 0 <= index < len(table):
        return table[index][1]
    return RACE_NAMES.get(index) or f"Race {index + 1}"


# speedrun.com spells one race differently from the game. Matching is done on
# a normalised name, and the handful that still differ are listed here rather
# than fuzzy-matched: a wrong match files a world record under another race.
NAME_ALIASES = {
    "solidersneaker": "soldiersneaker",
}


def _normalise(name: str) -> str:
    squashed = "".join(ch for ch in name.lower() if ch.isalnum())
    return NAME_ALIASES.get(squashed, squashed)


def race_index_by_name(name: str, game: str = "mm1", city: str = "") -> int:
    """The race index for a name, or -1.

    External leaderboards list the same races in a different order — the game
    goes Blitz, Circuit, Checkpoint and speedrun.com goes Blitz, Checkpoint,
    Circuit — so a record from elsewhere has to be placed by name. Position
    would silently file every Circuit time under a Checkpoint race.
    """
    if not name:
        return -1
    wanted = _normalise(name)
    for index, (_, known) in enumerate(_table(game, city)):
        if _normalise(known) == wanted:
            return index
    for index, known in RACE_NAMES.items():
        if _normalise(known) == wanted:
            return index
    return -1


def race_kind(index: int, game: str = "mm1", city: str = "") -> str:
    """Blitz, Circuit or Checkpoint. A 40s Blitz and a 4min Circuit are not
    the same achievement, so the board says which is which."""
    table = _table(game, city)
    if 0 <= index < len(table):
        return table[index][0]
    return RACE_KINDS.get(index, "")


@dataclass(frozen=True)
class LapRecord:
    """One time out of the game's own table."""

    slot: int
    driver: str
    car: str
    seconds: float
    city: str = ""
    difficulty: str = ""
    # Which game this came out of. Without it the record cannot name
    # its own race: the tables are per game and per city, and a record
    # that knows neither falls back to "Race 14".
    game: str = "mm1"

    @property
    def race(self) -> int:
        return self.slot // SLOTS_PER_RACE

    @property
    def race_name(self) -> str:
        return race_label(self.race, self.game, self.city)

    @property
    def kind(self) -> str:
        return race_kind(self.race, self.game, self.city)

    @property
    def car_name(self) -> str:
        return pretty_car(self.car)

    @property
    def vanilla_car(self) -> bool:
        return is_vanilla_car(self.car, self.game)

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

    def signature(self) -> tuple[float, str, str]:
        """What makes this entry itself, independent of which slot holds it.

        A race's entries are kept in time order, so the same lap moves slots
        as faster ones arrive above it. Identity has to come from the lap.
        """
        return (self.seconds, self.car.lower(), self.driver.lower())


def _string(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("latin-1", "replace").strip()


def parse(path: Path, city: str = "", difficulty: str = "",
          game: str = "mm1") -> list[LapRecord]:
    """Every usable record in one .dat file.

    Never raises on a bad file: a profile the launcher cannot read is a
    leaderboard with one fewer entry, not a crash on the way out of a game.
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return []
    spec = profiles.profile(game)
    if len(blob) < spec.header + RECORD:
        return []
    magic, _ = struct.unpack_from("<II", blob, 0)
    if magic != spec.magic:
        return []

    city = city or path.parent.name
    difficulty = difficulty or path.stem
    out: list[LapRecord] = []
    for slot in range((len(blob) - spec.header) // RECORD):
        start = spec.header + slot * RECORD
        chunk = blob[start : start + RECORD]
        if not struct.unpack("<I", chunk[_VALID])[0]:
            continue
        # The game's par time for the entry before it, not a lap anyone drove.
        if PAR_SLOTS_ARE_ODD and slot % 2:
            continue
        # Quantised on the way in. The file holds a float32, and every other
        # place a time is written — the store, the feed, a Discord message —
        # writes three decimals. Without rounding here the two disagree by up
        # to half a millisecond, the stored copy comes out *larger* than the
        # original, and every startup decides the same lap has just been
        # beaten: a duplicate record published on every launch, forever.
        seconds = round(struct.unpack("<f", chunk[_TIME])[0], 3)
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
                game=game,
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


def snapshot(install: Path, game: str = "mm1") -> dict[tuple[str, str, int], LapRecord]:
    """Every record in an install, keyed by the slot it sits in."""
    found: dict[tuple[str, str, int], LapRecord] = {}
    for path in record_files(install):
        for record in parse(path, game=game):
            found[record.key()] = record
    return found


def improvements(
    before: dict[tuple[str, str, int], LapRecord],
    after: dict[tuple[str, str, int], LapRecord],
) -> list[LapRecord]:
    """Entries that were not in the table before this session.

    Compared by content within a race, not slot by slot. Each race holds a
    small leaderboard kept in ascending order, so inserting a time pushes
    every slower entry down a slot. A slot-by-slot diff sees those shifts as
    new records and attributes each one to the car and driver that moved into
    the slot — reporting, for a single new lap, one genuine record and a
    string of invented ones.

    Comparing the set of (time, car, driver) a race held before against what
    it holds now leaves exactly the entries that are actually new.
    """
    previous: dict[tuple[str, str, int], set[tuple]] = {}
    for record in before.values():
        previous.setdefault(
            (record.city, record.difficulty, record.race), set()
        ).add(record.signature())

    out: list[LapRecord] = []
    for record in after.values():
        race_key = (record.city, record.difficulty, record.race)
        if record.signature() not in previous.get(race_key, ()):
            out.append(record)
    out.sort(key=lambda r: (r.city, r.difficulty, r.slot))
    return out
