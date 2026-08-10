"""Motocross Madness (1998).

A Rainbow Studios game rather than Angel Studios or Terminal Reality, and it
shows: there are no archives at all. Content sits as loose files in named
folders, and a track is a *set* of files sharing a stem —
`stadiums/pyrmid01.{scn,slt,tga}` for an arena, or
`teraform/canyon/canyon01.{dat,scn,tga,trn}` for an outdoor course.

Two consequences for the launcher, both worth being plain about:

* **No Options tab.** The game keeps no settings file. Its registry keys hold
  only install metadata — path, PID, language — and nothing a player would want
  to change. Rather than invent settings, this definition declares none.
* **No mod scanning.** Scanning needs either an archive format or a load-order
  list, and this game has neither. There is no way to tell a stock track from an
  added one by looking, so mods are imported explicitly and tracked by receipt,
  which is safe and honest. A packaged mod folder should mirror the game's own
  layout — `stadiums/mytrack.scn` and friends — so it lands in the right place.
"""

from __future__ import annotations

from .base import ExeTarget, GameDef, ModSpec

MCM1 = GameDef(
    id="mcm1",
    title="Motocross Madness",
    subtitle="Physics with no respect for your spine",
    year="1998",
    developer="Rainbow Studios",
    publisher="Microsoft",
    released="1998",
    genre="Off-road racing",
    setting="Deserts, quarries and stadium arenas",
    accent="#B04FC4",
    icon_shape="bike",
    description=(
        "Motocross Madness is remembered less for its racing than for its "
        "crashing. Rainbow Studios built a rider who ragdolls with real "
        "enthusiasm, and a physics model happy to fire him a hundred feet down "
        "a canyon while the bike cartwheels off somewhere else entirely.\n\n"
        "The racing underneath it is genuine: Supercross in tight stadium "
        "arenas, Nationals and Baja on open terrain you can leave the track on "
        "entirely, and a Stunt Quarry that exists purely so you can find out "
        "how far a hillside will throw you.\n\n"
        "Its open terrain was unusual for 1998 — courses are heightmaps you can "
        "ride off and explore, not ribbons between walls. Rainbow shipped the "
        "terrain and track editors with the game, and both are still sitting in "
        "this folder."
    ),
    extra_facts=(
        ("Renderer", "Direct3D Retained Mode"),
        ("Editors", "Teraform and TrakEdit, included"),
    ),
    exe_targets=(
        ExeTarget(
            id="retail",
            label="Motocross Madness",
            filename="mcm.exe",
            description=(
                "The 1998 executable. It renders through Direct3D Retained "
                "Mode, which modern drivers no longer implement, so the "
                "dgVoodoo wrapper in this folder is doing real work."
            ),
            recommended=True,
        ),
    ),
    signature_files=("mcm.exe",),
    # Loose content rather than archives, so detection checks a few files that
    # a complete install always has, across different content folders.
    data_files=(
        "maps/objects.cmp",
        "geometry/0.SLT",
        "stadiums/stddom01.scn",
        "lang.dll",
    ),
    notes=(
        "Motocross Madness stores no settings of its own — its registry keys "
        "hold install metadata only — so there is nothing for the Options tab "
        "to edit.\n\n"
        "It has no archive format either. Tracks are sets of loose files: a "
        "stadium is stadiums/<name>.scn with matching .slt and .tga, and an "
        "outdoor course is teraform/<category>/<name>.scn with .dat, .tga and "
        ".trn beside it. A mod folder should mirror that layout so its files "
        "land where the game looks for them."
    ),
    mod_spec=ModSpec(
        # The .scn identifies a track; the rest of the set travels with it.
        archive_suffixes=(".scn",),
        priority_prefix="",
        max_priority=0,
        # Nothing to scan: no archive format and no load-order list means a
        # stock track and an added one are indistinguishable on disk. Offering
        # a scan button would list the entire base game as removable "mods".
        scan_staging=False,
        content_dirs=("stadiums", "teraform"),
        content_help=(
            "Stadium tracks live in stadiums/, and outdoor courses under teraform/<category>/. A downloaded track is just a file, so the launcher asks where it belongs."
        ),
        notes=(
            "Import a mod as a folder laid out like the game itself, so that "
            "stadiums/ and teraform/ files land where they belong. Enabling "
            "copies them in and records exactly what was written; disabling "
            "puts back anything they replaced."
        ),
    ),
)
