"""Game description types.

A game is data, not code: adding Motocross Madness or Monster Truck Madness
means writing another GameDef, not touching the UI or the mod manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExeTarget:
    """One launchable executable inside a game folder."""

    id: str
    label: str
    filename: str
    description: str = ""
    recommended: bool = False
    # False when the game's option set belongs to a different build than this
    # executable, e.g. a reimplementation's extra flags versus the retail exe.
    options_apply: bool = True
    # Shown on the Options tab when options_apply is False.
    options_caveat: str = ""
    # Files this executable leaves beside it. If the executable is gone but
    # these remain, it was removed from an install that once had it — worth
    # saying so, rather than silently pretending the build was never there.
    residue_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptionSpec:
    """A launch setting that maps onto a real command-line argument.

    kind is one of "bool", "int", "choice". Booleans follow the AGE-engine
    convention of `-name` / `-noname`; ints and choices emit `-name value`.
    """

    key: str
    label: str
    kind: str
    default: Any
    group: str = "General"
    help: str = ""
    choices: tuple[tuple[str, Any], ...] = ()
    minimum: int = 0
    maximum: int = 9999
    # False for flags the engine can only switch ON. Open1560 has two kinds of
    # argument: cmd_param, which understands `-noflag`, and plain argv scans
    # (`ARG("-allcars")`) which latch a variable to true and have no negation.
    # Emitting `-noallcars` for the latter would be silently ignored, and worse,
    # the flag cannot be undone if something else on the command line set it.
    negatable: bool = True
    # When set, this option lives in the game's config file under this section
    # rather than on the command line. Games like MM2 configure their mod hook
    # through an INI, and there is no argument to emit at all.
    ini_section: str = ""
    # Key name in that file, when it differs from `key`.
    ini_key: str = ""
    # Decimal places for float options; 0 means the option is an integer.
    decimals: int = 0
    step: float = 1.0
    # Values the game actually supports. A value outside this set is flagged in
    # the UI with `invalid_help`, rather than silently producing a broken game.
    valid_values: tuple = ()
    invalid_help: str = ""

    @property
    def is_ini(self) -> bool:
        return bool(self.ini_section)

    def file_key(self) -> str:
        return self.ini_key or self.key


@dataclass(frozen=True)
class PathSetting:
    """A config key that must point back into the game's own folder.

    Installers of this era wrote absolute paths into their INI files, so moving
    or copying a game folder silently breaks it: the game keeps looking where it
    was installed. Monster Truck Madness fails with "Unable to open cockpit
    file" because its cockpit art is loaded relative to a CDROMPath that no
    longer exists. The launcher knows where the game actually is, so it can spot
    and repair these.
    """

    section: str
    key: str
    # Path relative to the game folder that this key should hold. Empty means
    # the game folder itself.
    target: str = ""
    label: str = ""

    def expected(self, root) -> str:
        from pathlib import Path

        base = Path(root)
        return str(base / self.target if self.target else base)


@dataclass(frozen=True)
class ModSpec:
    """How mods are packaged and prioritised for a given game."""

    # Archive extensions the game loads directly from its root folder.
    archive_suffixes: tuple[str, ...] = (".ar",)
    # Character repeated to raise load priority (MM1: "!" sorts earlier).
    priority_prefix: str = ""
    max_priority: int = 0
    priority_help: str = ""
    notes: str = ""
    # Whether to offer scanning the game folder for mods parked in subfolders.
    # Distributions ship hundreds of megabytes that way, so they are indexed in
    # place rather than copied.
    #
    # Which folders those are is discovered, not configured: any subfolder
    # holding archives counts. Packs rename their mod folders freely — the same
    # MM2 install went from "1 Additional cars" to "Addon Cars" between two
    # sittings — so a hardcoded list is guaranteed to rot.
    scan_staging: bool = False
    # Subfolders the game itself owns, which never hold mods to be indexed.
    staging_exclude: tuple[str, ...] = (
        "system", "players", "tools", "lua", "dev", "mods", "crashes",
        "music", "netlogs", "ai_path_logs", "screenshots", "replays",
        "backups", "setup", "tourney", "videos", "levelcache", "dgvoodoo",
    )
    staging_help: str = ""
    # Some engines keep load order in a list file rather than in filenames.
    # When set, enabling a mod registers its archives here; an archive already
    # inside the game folder is referenced where it sits, not copied.
    order_file: str = ""
    order_help: str = ""
    # Folders holding loose content, for games with no archive format. A course
    # or track downloaded on its own is just a file; it means nothing until it
    # is in the right folder, and only the player knows which discipline it is
    # for. These roots are scanned for the folders to offer as destinations.
    content_dirs: tuple[str, ...] = ()
    content_help: str = ""


@dataclass(frozen=True)
class GameDef:
    id: str
    title: str
    subtitle: str
    year: str
    developer: str
    accent: str
    exe_targets: tuple[ExeTarget, ...]
    # Any one of these proves the folder is this game.
    signature_files: tuple[str, ...]
    # Which executable carries the artwork, when the first playable one does
    # not: a portable build's launcher wrapper often has a generic icon while
    # the real binary beside it has the game's own. Empty means "try them in
    # order".
    icon_exe: str = ""
    # Silhouette drawn when the game has not been set up yet and there is no
    # executable to read an icon from: "car", "truck" or "bike".
    icon_shape: str = "car"
    # Data the game cannot start without; missing ones are surfaced as warnings.
    data_files: tuple[str, ...] = ()
    options: tuple[OptionSpec, ...] = ()
    mod_spec: ModSpec = field(default_factory=ModSpec)
    # File the engine also reads arguments from, if any.
    args_file: str | None = None
    # INI the game (or its mod hook) reads its settings from. Options carrying
    # an ini_section are read from and written to this file.
    options_file: str | None = None
    # Shown when options_file is expected but absent.
    options_file_hint: str = ""
    # Keys in options_file holding absolute paths into the game's own folder.
    path_settings: tuple[PathSetting, ...] = ()
    # A mod hook loaded into the game at launch, and the helper that loads it.
    # Both must sit in the game folder. Used when the game has no free DLL slot
    # to proxy — Monster Truck Madness's DDRAW.dll is taken by dgVoodoo.
    hook_dll: str = ""
    injector: str = ""
    hook_name: str = ""
    # Games whose physics assume one CPU and a millisecond clock. See
    # launch.pin_to_single_core for why this is not optional for some of them.
    needs_single_core: bool = False
    single_core_reason: str = ""
    notes: str = ""
    # Overview-tab material. All optional: a game defined without them simply
    # shows a thinner Overview.
    publisher: str = ""
    released: str = ""
    genre: str = ""
    setting: str = ""
    description: str = ""
    # Extra key/value rows for the fact table, appended after the standard ones.
    extra_facts: tuple[tuple[str, str], ...] = ()

    def facts(self) -> list[tuple[str, str]]:
        rows = [
            ("Developer", self.developer),
            ("Publisher", self.publisher),
            ("Released", self.released or self.year),
            ("Genre", self.genre),
            ("Setting", self.setting),
        ]
        rows.extend(self.extra_facts)
        return [(k, v) for k, v in rows if v]

    def target(self, target_id: str) -> ExeTarget | None:
        for t in self.exe_targets:
            if t.id == target_id:
                return t
        return None

    def default_target(self) -> ExeTarget:
        for t in self.exe_targets:
            if t.recommended:
                return t
        return self.exe_targets[0]

    def option(self, key: str) -> OptionSpec | None:
        for o in self.options:
            if o.key == key:
                return o
        return None

    def option_groups(self) -> list[str]:
        seen: list[str] = []
        for o in self.options:
            if o.group not in seen:
                seen.append(o.group)
        return seen


def build_args(game: GameDef, values: dict[str, Any], extra: str = "") -> list[str]:
    """Turn stored option values into an argv list.

    Only values that differ from the game's default are emitted, so the command
    line stays short and the engine's own defaults keep applying.
    """
    args: list[str] = []
    for spec in game.options:
        # INI-backed options are written to the config file, never emitted here.
        if spec.is_ini or spec.key not in values:
            continue
        value = values[spec.key]
        if value is None or value == spec.default:
            continue
        if spec.kind == "bool":
            if value:
                args.append(f"-{spec.key}")
            elif spec.negatable:
                args.append(f"-no{spec.key}")
            # else: an on-only flag being switched off emits nothing, since
            # `-noflag` would not be understood.
        else:
            args.append(f"-{spec.key}")
            args.append(str(value))
    if extra.strip():
        args.extend(extra.split())
    return args
