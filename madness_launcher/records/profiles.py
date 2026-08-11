"""What differs between one game's record tables and another's.

Midtown Madness and Midtown Madness 2 store records in almost the same way —
132-byte entries, ten slots per race, even sub-slots real and odd ones par
times, five sorted entries per race with the car bound to each. Everything
that actually differs lives here, so the reading and judging code is written
once.

The differences are small in number and large in consequence:

    header      MM1 has 8 bytes before the first record, MM2 has 16
    magic       1234 against 1
    cities      one (chicago) against two (london, sf)
    race order  MM1 runs Blitz, Circuit, Checkpoint; MM2 is the reverse
    cars        different rosters
    archives    MM1 allows four fixes by content hash, MM2 allows any
                archive whose name begins with mm2
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import mm2tables

# MM1's stock roster, read out of its ui.ar. See reader.CAR_NAMES for the
# descriptions the game gives them.
MM1_CARS = (
    "vpbug", "vpbullet", "vpbus", "vpcaddie", "vpcop",
    "vpford", "vpmustang99", "vppanoz", "vppanozgt", "vpsemi",
)

# MM2's stock roster, taken from the tune/*.info entries in a stock
# mm2core.ar — the same place the game looks for a car's handling.
MM2_CARS = (
    "VPCOOP", "vp4x4", "vpauditt", "vpbug", "vpbullet", "vpbus", "vpcab",
    "vpcaddie", "vpcentury", "vpcoop2k", "vpcop", "vpdb7", "vpddbus",
    "vpdune", "vpford", "vpmustang99", "vppanoz", "vppanozgt", "vpsemi",
    "vpvwcup",
)

# The four fixes allowed on MM1's vanilla board, by content hash. Named by
# hash and not by filename because load order is set by leading '!', so the
# same mod legitimately appears under many names — and renaming a handling
# mod to wsfix16to9.ar would otherwise be all it took to reach the board.
MM1_VANILLA_ARCHIVES = {
    "6e369662d58cabaa5823698926b5af9c37e8c16536e8c140fb917adeeee0a911": "VanillaHLFix",
    "0d705e111e104884cece44e95f39bf74cd272c7fbe02640ab280e60465799f4c": "kbmousepad",
    "415dc193a5e4748ea4a1cda34394111fdd530f981890f1f35170587c15d355d1": "wsfix16to9",
    "3383ab0b7e38df92e9ec856726b80c39e6ff2d5581748afaefc06141e906942e": "mousemod",
}


@dataclass(frozen=True)
class GameProfile:
    """Everything about one game's record tables that is not shared."""

    game_id: str
    header: int
    magic: int
    cities: tuple[str, ...]
    vanilla_cars: frozenset[str]
    # Archives the game ships with, never counted as somebody's addition.
    base_archives: frozenset[str]
    # city -> ordered (kind, race name); the index is the race index.
    races: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    # Added archives allowed on the vanilla board, by content hash.
    vanilla_archives: dict[str, str] = field(default_factory=dict)
    # Or, instead of hashes, a filename prefix that counts as stock.
    #
    # Weaker than hashing and deliberately so, because it is what MM2's owner
    # asked for: the game's own archives are all named mm2*, and anything else
    # is somebody's addition. The cost is that the check is on the name, so
    # renaming a handling mod to mm2handling.ar would pass it. Hashing cannot
    # be used here the way it is for MM1, because MM1 allows four specific
    # known files whereas this allows a whole family whose contents differ
    # between installs and game versions.
    stock_prefix: str = ""

    def race_table(self, city: str) -> tuple[tuple[str, str], ...]:
        return self.races.get(city.lower(), ())


MM1 = GameProfile(
    game_id="mm1",
    header=8,
    magic=1234,
    cities=("chicago",),
    vanilla_cars=frozenset(c.lower() for c in MM1_CARS),
    base_archives=frozenset({"core.ar", "audio.ar", "ui.ar", "1560.ar"}),
    vanilla_archives=MM1_VANILLA_ARCHIVES,
)

MM2 = GameProfile(
    game_id="mm2",
    header=16,
    magic=1,
    cities=("london", "sf"),
    vanilla_cars=frozenset(c.lower() for c in MM2_CARS),
    # Every stock archive is mm2-prefixed, so the prefix rule covers them and
    # this stays empty rather than duplicating the list.
    base_archives=frozenset(),
    races=dict(mm2tables.RACES),
    stock_prefix="mm2",
)

PROFILES: dict[str, GameProfile] = {"mm1": MM1, "mm2": MM2}


def profile(game_id: str) -> GameProfile:
    """The profile for a game, falling back to MM1's shape.

    MM1 is the fallback because its layout is the one the reader was written
    against; a game with no profile at least parses rather than raising.
    """
    return PROFILES.get(game_id, MM1)
