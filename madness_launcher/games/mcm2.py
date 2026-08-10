"""Motocross Madness 2 (2000).

The sequel to Rainbow Studios' first Motocross Madness, and it keeps that
game's shape: loose content in named folders rather than archives. Courses are
`.env` files under `TERAFORM/<category>/`, with bike and rider skins alongside.

This is the portable distribution, which matters for how it starts. The game
keeps its configuration in the registry, and a portable copy has no installer to
put it there — so `Play MCM2.exe` loads `mcm2_profile.json` into the registry
first and then starts the game. Launching `Mcm2.exe` directly skips that, which
is why it is offered second rather than first.

As with the first game there is no Options tab: `mcm2_profile.json` holds video
card profiles and controller GUIDs as raw registry blobs, not settings a player
would sit and tune.
"""

from __future__ import annotations

from .base import ExeTarget, GameDef, ModSpec

MCM2 = GameDef(
    id="mcm2",
    title="Motocross Madness 2",
    subtitle="More air, more ways to land wrong",
    year="2000",
    developer="Rainbow Studios",
    publisher="Microsoft",
    released="2000",
    genre="Off-road racing",
    setting="Baja, national circuits and stadium arenas",
    accent="#D0455B",
    icon_shape="bike",
    icon_exe="Mcm2.exe",
    description=(
        "Motocross Madness 2 does what the first game did, with more of "
        "everything and a far better idea of what people actually enjoyed "
        "about it. The rider still ragdolls spectacularly, the terrain is still "
        "open enough to leave the course entirely, and the crashes are still "
        "the part you replay.\n\n"
        "Baja, Nationals, Supercross, Enduro and Stunt Quarry each ask for "
        "something different — Enduro in particular is long, technical and "
        "unforgiving in a way arena racing never is. Multiplayer and a replay "
        "system round it out, and the game keeps ghost files so you can race "
        "your own best runs.\n\n"
        "It has stayed alive on community terrain. Courses are plain files in "
        "TERAFORM, so people never stopped building them."
    ),
    extra_facts=(
        ("Renderer", "Direct3D Retained Mode"),
        ("Courses", "TERAFORM/*.env"),
    ),
    exe_targets=(
        ExeTarget(
            id="portable",
            label="Play MCM2 (portable launcher)",
            filename="Play MCM2.exe",
            description=(
                "The right entry point for this copy. It writes the settings "
                "from mcm2_profile.json into the registry — which a portable "
                "install has no other way to do — and then starts the game."
            ),
            recommended=True,
        ),
        ExeTarget(
            id="retail",
            label="Mcm2.exe (directly)",
            filename="Mcm2.exe",
            description=(
                "Starts the game without loading mcm2_profile.json first. Use "
                "this only if the settings are already in your registry; "
                "otherwise the game may not find a usable display mode."
            ),
        ),
    ),
    signature_files=("Mcm2.exe", "MCM2.ICD"),
    data_files=("RES/BIKE.RES", "RES/AUDIO.RES", "UI/CURSOR.TGA", "LANG.DLL"),
    notes=(
        "Motocross Madness 2 keeps its configuration in the registry. In this "
        "portable copy that lives in mcm2_profile.json, which Play MCM2.exe "
        "loads before starting the game — so launch through that rather than "
        "Mcm2.exe.\n\n"
        "The profile holds video card capability profiles and controller GUIDs "
        "as raw registry blobs, not the kind of settings worth editing by hand, "
        "so the launcher does not offer an Options tab for this game."
    ),
    mod_spec=ModSpec(
        # Courses are .env files; bike and rider skins are loose textures.
        archive_suffixes=(".env",),
        priority_prefix="",
        max_priority=0,
        # No archive format and no load-order list, so a stock course and an
        # added one look identical on disk. Scanning would offer the base game
        # for deletion; mods are imported explicitly instead.
        scan_staging=False,
        content_dirs=("TERAFORM",),
        content_help=(
            "Courses are .env files under TERAFORM, grouped by discipline - SX for Supercross, NATIONAL, BAJA, ENDURO, QUARRIES and TAG. A downloaded course is just a file, so the launcher asks which one it belongs to."
        ),
        notes=(
            "Courses live in TERAFORM/<category>/ as .env files, with bike and "
            "rider skins in BIKES/ and RIDERS/. Import a mod as a folder laid "
            "out the same way so its files land where the game looks for them."
        ),
    ),
)
