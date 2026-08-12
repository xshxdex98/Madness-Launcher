"""Reading Motocross Madness 2's own best-time tables.

Nothing like the Midtown games. Those are one AGE engine with a save file of
fixed-size records; this is Rainbow Studios, and a track's times live beside
the track as `<track>.hs1`, 208 bytes:

    [0:4]   a small integer, constant per discipline in every file seen
    [4:8]   how many of the ten slots are filled
    [8:...] ten slots of a 16-byte NUL-padded rider name and a float32 of
            seconds, sorted fastest first, 0x7F7FFFFF meaning empty

The discipline comes free: tracks live in TERAFORM/<discipline>/, which is
also how the game groups them — SX, NATIONAL, ENDURO, BAJA, QUARRIES, TAG.

A time is the FASTEST LAP, not the race. Confirmed on a three-lap Supercross
at Week 01 - Seattle, which stored 1:12.909 — one lap of it. This is worth
being sure of rather than assuming: Midtown Madness 2 turned out to store
circuit times per lap while speedrun.com times the whole race, the two are
not comparable, and a board was built on the mistake before anyone noticed.
Every Motocross time on the board is one lap, so they all mean the same
thing however many laps were ridden to set them.

Two things this format does not give us.

The bike class is not in a slot; there is room for a name and a time and
nothing else. See `selected_class`.

The track's real name is not obtainable. The .env files are encrypted — magic
`FAOE!`, near eight bits of entropy a byte, and not one printable run of six
characters in a seventeen-megabyte file — and the names are not in LANG.DLL
either, which holds only the descriptions. So a track is named by its
filename until the rider profile tells us better; see `profile_names`.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path

HEADER = 8
SLOT = 20
NAME_BYTES = 16
SLOTS = 10
# The empty-slot sentinel, 0x7F7FFFFF, is 3.4e38. Anything near it is not a
# lap; anything over an hour is not one either.
MAX_TIME = 3600.0

BOARD_VANILLA = "vanilla"
BOARD_MODDED = "modded"

# Folder name -> what the game calls that kind of racing.
DISCIPLINES = {
    "SX": "Supercross",
    "NATIONAL": "Nationals",
    "ENDURO": "Enduro",
    "BAJA": "Baja",
    "QUARRIES": "Stunt Quarry",
    "TAG": "Tag",
}

# The engine classes, exactly as LANG.DLL names them ("Up to 125cc" and so on).
CLASSES = (125, 250, 350, 500, 600)

# The fifty-one tracks Motocross Madness 2 shipped with, which is what makes a
# board "vanilla tracks". Held by name because the alternative is hashing
# fifty-one files of seven to seventeen megabytes on every check — a third of
# a gigabyte of reading to answer a question about a filename. Size is carried
# alongside as a cheap second opinion, so a community track dropped in as
# NAT05.env does not quietly inherit a stock track's standing.
STOCK_TRACKS: dict[str, tuple[str, int]] = {
    "baja01": ("BAJA", 14162022),
    "baja02": ("BAJA", 14768661),
    "baja03": ("BAJA", 13233792),
    "baja04": ("BAJA", 13005073),
    "baja05": ("BAJA", 14613091),
    "airfield": ("ENDURO", 15755035),
    "farm": ("ENDURO", 17079150),
    "openpit": ("ENDURO", 16523753),
    "skilodge": ("ENDURO", 15004389),
    "trailer": ("ENDURO", 17290637),
    "chanos": ("NATIONAL", 7052124),
    "hillside": ("NATIONAL", 7244038),
    "iffendic": ("NATIONAL", 6888925),
    "nat01": ("NATIONAL", 6838542),
    "nat02": ("NATIONAL", 6835436),
    "nat03": ("NATIONAL", 7267526),
    "nat04": ("NATIONAL", 6864840),
    "nat05": ("NATIONAL", 6780832),
    "nat06": ("NATIONAL", 6868221),
    "nat07": ("NATIONAL", 7006114),
    "nat08": ("NATIONAL", 6692360),
    "nat09": ("NATIONAL", 6850711),
    "nat10": ("NATIONAL", 6675385),
    "nat11": ("NATIONAL", 7105153),
    "nat12": ("NATIONAL", 7132415),
    "vv": ("NATIONAL", 6645180),
    "quarry01": ("QUARRIES", 13839581),
    "quarry02": ("QUARRIES", 12045063),
    "quarry03": ("QUARRIES", 12206084),
    "quarry04": ("QUARRIES", 12478650),
    "quarry05": ("QUARRIES", 12977571),
    "sx01": ("SX", 4232798),
    "sx02": ("SX", 4000693),
    "sx03": ("SX", 3991533),
    "sx04": ("SX", 3977631),
    "sx05": ("SX", 3658872),
    "sx06": ("SX", 4050515),
    "sx07": ("SX", 3715559),
    "sx08": ("SX", 3954939),
    "sx09": ("SX", 3970360),
    "sx10": ("SX", 3834028),
    "sx11": ("SX", 3484598),
    "sx12": ("SX", 3947070),
    "sx13": ("SX", 3784775),
    "sx14": ("SX", 3978253),
    "sx15": ("SX", 4166281),
    "sx16": ("SX", 4033970),
    "sx17": ("SX", 3787521),
    "tag01": ("TAG", 4007226),
    "tag02": ("TAG", 4031306),
    "tag03": ("TAG", 3923789),
}


def discipline(folder: str) -> str:
    """The label for a TERAFORM subfolder."""
    return DISCIPLINES.get(folder.upper(), folder.title())


def is_stock(stem: str, folder: str = "", size: int = 0) -> bool:
    """Whether a track is one the game shipped with.

    The size check is advisory: it only rejects, and only when a size is both
    known and given, so a track we have no recorded size for still passes on
    its name. Better a stock track wrongly on the modded board than someone's
    handiwork sitting on the vanilla one.
    """
    entry = STOCK_TRACKS.get(stem.lower())
    if entry is None:
        return False
    want_folder, want_size = entry
    if folder and folder.upper() != want_folder:
        return False
    return not (size and want_size and size != want_size)


def classify(stem: str, folder: str = "", size: int = 0) -> str:
    """Which board a time on this track belongs to."""
    return BOARD_VANILLA if is_stock(stem, folder, size) else BOARD_MODDED


_WORD = re.compile(r"[_\s]+")

# Real names, once anybody's launcher has learned one. Keyed by lowercased
# filename stem. Installed at startup from the saved map and topped up as
# tracks are ridden; see learn_name.
_LEARNED: dict[str, str] = {}


def set_learned(names: dict[str, str]) -> None:
    """Install the known track names. Replaces whatever was there."""
    _LEARNED.clear()
    _LEARNED.update({str(k).lower(): str(v) for k, v in (names or {}).items() if v})


def learned_names() -> dict[str, str]:
    return dict(_LEARNED)


def pretty_track(stem: str) -> str:
    """A readable name for a track.

    The real names are locked inside the encrypted .env, so this falls back
    to the filename until the rider profile has supplied a better one. The
    fallback is often exactly right already — TD_Making_Tracks is displayed
    by the game as "TD Making Tracks".
    """
    known = _LEARNED.get(stem.strip().lower())
    if known:
        return known
    name = _WORD.sub(" ", stem.strip()).strip()
    return name or stem


def track_index(stem: str) -> int:
    """A stable number for a track, derived only from its name.

    The rest of the records system identifies a race by an index into a fixed
    table. Motocross Madness has no fixed table: a track is a file somebody
    downloaded, so no two installs agree on an ordering and an index derived
    from one machine's folder listing would name a different track on the
    next. Hashing the name gives every install the same answer without any
    of them having to agree on anything first.
    """
    digest = hashlib.sha1(stem.strip().lower().encode("utf-8")).hexdigest()
    # 28 bits, comfortably inside a JSON-safe int and far short of collision
    # trouble across the low thousands of tracks that exist.
    return int(digest[:7], 16)


@dataclass
class MotoRecord:
    """One time out of a track's own table."""

    track: str
    folder: str
    driver: str
    seconds: float
    bike_class: str = ""
    stock: bool = True
    game: str = "mcm2"

    @property
    def race(self) -> int:
        return track_index(self.track)

    @property
    def race_name(self) -> str:
        return pretty_track(self.track)

    @property
    def kind(self) -> str:
        return discipline(self.folder)

    @property
    def board(self) -> str:
        return BOARD_VANILLA if self.stock else BOARD_MODDED

    @property
    def formatted(self) -> str:
        minutes, seconds = divmod(self.seconds, 60)
        if minutes:
            return f"{int(minutes)}:{seconds:06.3f}"
        return f"{seconds:.3f}"

    def key(self) -> tuple[str, str]:
        """The track this record sits on, ignoring which slot holds it."""
        return (self.folder.upper(), self.track.lower())

    def signature(self) -> tuple[float, str]:
        """What makes this entry itself, independent of its slot.

        A track's ten entries are kept in time order, so an existing lap
        slides down as faster ones arrive above it. Comparing by position
        reports every one of those as a new record — which is exactly what
        Midtown Madness did until it was compared by content instead.
        """
        return (self.seconds, self.driver.lower())


def parse(path: Path) -> list[MotoRecord]:
    """Every usable entry in one .hs1.

    Never raises. A table the launcher cannot read is a board with one fewer
    row, not a crash on the way out of a game.

    Strict about what it accepts, because the far side of this is a public
    board. The header says how many of the ten slots are filled, and that
    count is exact in every real file; the slots past it hold uninitialised
    memory. Reading all ten and keeping whatever looked like a float in range
    turned 96 out of every 100 random blobs into a record. Honouring the count
    and insisting a rider name is printable takes that to none.
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return []
    if len(blob) < HEADER + SLOTS * SLOT:
        return []
    _, count = struct.unpack_from("<2I", blob, 0)
    if not 0 < count <= SLOTS:
        # Not a table in the shape this game writes.
        return []

    folder = path.parent.name
    stem = path.stem
    stock = is_stock(stem, folder, _env_size(path))
    out: list[MotoRecord] = []
    for i in range(count):
        off = HEADER + i * SLOT
        raw = blob[off : off + NAME_BYTES].split(b"\0")[0]
        seconds = struct.unpack_from("<f", blob, off + NAME_BYTES)[0]
        # Quantised here, once. Midtown Madness stored 120.042 against a real
        # 120.0417709 and produced six phantom improvements on every startup
        # for want of this.
        seconds = round(seconds, 3)
        if not (0 < seconds <= MAX_TIME):
            continue
        try:
            driver = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            continue
        if not driver or not driver.isprintable():
            continue
        out.append(
            MotoRecord(
                track=stem,
                folder=folder,
                driver=driver,
                seconds=seconds,
                stock=stock,
            )
        )
    return out


def _env_size(hs1: Path) -> int:
    """The size of the track this table belongs to, if it is still there."""
    for suffix in (".env", ".ENV"):
        candidate = hs1.with_suffix(suffix)
        try:
            return candidate.stat().st_size
        except OSError:
            continue
    return 0


def terraform(install: Path) -> Path:
    return Path(install) / "TERAFORM"


def record_files(install: Path) -> list[Path]:
    root = terraform(install)
    if not root.is_dir():
        return []
    try:
        return sorted(root.rglob("*.hs1"))
    except OSError:
        return []


def snapshot(install: Path, game: str = "mcm2") -> dict[tuple, MotoRecord]:
    """Every recorded time in the install, keyed by track and slot order."""
    out: dict[tuple, MotoRecord] = {}
    for path in record_files(Path(install)):
        for index, record in enumerate(parse(path)):
            record.game = game
            out[(*record.key(), index)] = record
    return out


def improvements(
    before: dict[tuple, MotoRecord], after: dict[tuple, MotoRecord]
) -> list[MotoRecord]:
    """Entries in `after` that were not in `before`, compared by content.

    Grouped by track rather than by slot, for the reason in `signature`.
    """
    previous: dict[tuple[str, str], set] = {}
    for record in before.values():
        previous.setdefault(record.key(), set()).add(record.signature())
    out = [
        r
        for r in after.values()
        if r.signature() not in previous.get(r.key(), ())
    ]
    out.sort(key=lambda r: (r.folder, r.track, r.seconds))
    return out


# ----------------------------------------------------------------------
# Track names, learned from the rider profile
# ----------------------------------------------------------------------

# The profile keeps a short list of recently ridden tracks as 128-byte
# records. It is the only place on disk a track's real name appears in the
# clear. The name sits 28 bytes into each record, NUL-terminated, with the
# author's name after it.
PROFILE_RECORD = 128
PROFILE_FIRST = 64
PROFILE_NAME_AT = 28
PROFILE_NAME_MAX = 48
PROFILE_SLOTS = 6


def profile_files(install: Path) -> list[Path]:
    root = Path(install) / "UI" / "PROFILE"
    if not root.is_dir():
        return []
    try:
        return sorted(root.glob("*/*.prf"))
    except OSError:
        return []


def profile_names(path: Path) -> list[str]:
    """The display names in one rider profile's recent-tracks list."""
    try:
        blob = path.read_bytes()
    except OSError:
        return []
    out = []
    for i in range(PROFILE_SLOTS):
        off = PROFILE_FIRST + i * PROFILE_RECORD + PROFILE_NAME_AT
        if off + PROFILE_NAME_MAX > len(blob):
            break
        text = (
            blob[off : off + PROFILE_NAME_MAX]
            .split(b"\0")[0]
            .decode("latin-1", "replace")
            .strip()
        )
        if text and text.isprintable():
            out.append(text)
    return out


def all_profile_names(install: Path) -> list[str]:
    """Recent-track names across every rider profile in the install."""
    seen: list[str] = []
    for path in profile_files(install):
        for name in profile_names(path):
            if name not in seen:
                seen.append(name)
    return seen


def learn_name(
    changed: list[str], before: list[str], after: list[str]
) -> tuple[str, str] | None:
    """Pair a track filename with the real name the game shows for it.

    The names in the profile carry no filename, and the filenames elsewhere in
    it are fragments of a fixed-size array rather than a list worth trusting.
    So the pairing is made from behaviour instead: the launcher already knows
    which tracks gained a time this session, and the profile already knows
    which track was ridden. When both say exactly one thing, they are saying
    it about the same track.

    Deliberately gives up when either side is ambiguous. A wrong name would
    travel through the feed to everybody, and is worse than no name at all.
    """
    if len(changed) != 1:
        return None
    fresh = [n for n in after if n not in before]
    if not fresh and after:
        # Nothing new, but the list reorders as tracks are ridden: the one
        # just played moves to the front.
        fresh = after[:1] if after[:1] != before[:1] else []
    if len(fresh) != 1:
        return None
    name = fresh[0].strip()
    stem = changed[0]
    if not name or name.lower() == pretty_track(stem).lower():
        return None
    return stem, name


# Where the rider profile keeps the engine size of the selected bike.
#
# Found by riding, not by reading: a 125cc lap on SX01 turned this word from
# 250 to 125, and of the 1190 words in the profile it was the only one that
# moved to a value in CLASSES. The bike's texture changed from KTM250SX to
# KTM125SX in the same write, which says the same thing twice.
PROFILE_CLASS_AT = 2328


def profile_class(path: Path) -> int:
    """The engine size on one rider profile, or 0 if it does not look like one."""
    try:
        blob = path.read_bytes()
    except OSError:
        return 0
    if len(blob) < PROFILE_CLASS_AT + 4:
        return 0
    value = struct.unpack_from("<I", blob, PROFILE_CLASS_AT)[0]
    return value if value in CLASSES else 0


def selected_class(install: Path) -> str:
    """The engine class currently chosen, as "125cc", or empty if unknown.

    A profile-wide selection rather than something stored against each time,
    because the game does not record a class in the table — a slot holds a
    name and a time and nothing else. So this is the class that was selected
    when the game last wrote its profile, which for a session the launcher
    watched is the class the session was ridden on.

    The honest limit: change bike between two races in one sitting and both
    times take the class of the second. Nothing on disk can distinguish them.

    Returns empty rather than a guess when the profile cannot be read, and
    the board shows no class rather than a wrong one.
    """
    sizes = {profile_class(p) for p in profile_files(Path(install))}
    sizes.discard(0)
    # More than one profile with different bikes: no way to say which rode.
    if len(sizes) != 1:
        return ""
    return f"{sizes.pop()}cc"
