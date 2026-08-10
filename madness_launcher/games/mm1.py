"""Midtown Madness (1999).

Options below are taken from the Open1560 argument reference (docs/setup.md in
the Open1560 tree). Defaults mirror the engine's own defaults so that an
unmodified profile emits an empty command line.
"""

from __future__ import annotations

from .base import ExeTarget, GameDef, ModSpec, OptionSpec

MM1 = GameDef(
    id="mm1",
    title="Midtown Madness",
    subtitle="Chicago, open world, no rules",
    year="1999",
    developer="Angel Studios",
    publisher="Microsoft",
    released="May 1999",
    genre="Open-world arcade racing",
    setting="Chicago, Illinois",
    accent="#E0912F",
    icon_shape="car",
    description=(
        "Midtown Madness drops you into an open recreation of Chicago and, "
        "unusually for 1999, simply lets you drive. There are no invisible "
        "walls funnelling you along a ribbon of track: the Loop, the river "
        "bridges and the lakefront are all continuous, populated with traffic "
        "that obeys the lights, pedestrians that scatter, and police who take "
        "an interest in how you are driving.\n\n"
        "Races come in four shapes. Blitz sends you through a sequence of "
        "checkpoints against the clock, Circuit runs laps of a closed course, "
        "Checkpoint is a straight dash to a finish with the route left to you, "
        "and Cruise is no race at all — the city, no timer, nothing to win. "
        "That last mode is the one the game is remembered for, and the reason "
        "people still load it up.\n\n"
        "Weather, time of day and traffic density are yours to set before you "
        "start, and they change the city rather than just its lighting: wet "
        "asphalt genuinely costs you grip. Multiplayer put up to eight drivers "
        "in the same Chicago, including a game of tag played in city buses."
    ),
    extra_facts=(
        ("Engine", "Angel Game Engine (AGE)"),
        ("Modern build", "Open1560"),
    ),
    exe_targets=(
        ExeTarget(
            id="open1560",
            label="Open1560",
            filename="Open1560.exe",
            description=(
                "Modern reimplementation. Native resolutions, no dgVoodoo or XP "
                "patch needed. Recommended."
            ),
            recommended=True,
            residue_files=(
                "Open1560.log",
                "Open1560.map",
                "Open1560.pdb",
                "SDL3.dll",
            ),
        ),
        ExeTarget(
            id="retail",
            label="Original (MIDTOWN.exe)",
            filename="MIDTOWN.exe",
            description="The 1999 retail executable. May need a DirectDraw wrapper.",
            options_apply=False,
            options_caveat=(
                "Most options here are Open1560 additions — resolution, "
                "anti-aliasing, vsync, frame limiting, mouse mode and the "
                "renderer flags do nothing on the retail executable. The "
                "original debug flags such as -allcars, -allrace and -nodamage "
                "still apply."
            ),
        ),
    ),
    # Any one of these identifies the folder as Midtown Madness.
    signature_files=("Open1560.exe", "MIDTOWN.exe", "MIDTOWN.icd"),
    # Per Open1560 setup docs, these three archives are the minimum data set.
    data_files=("core.ar", "audio.ar", "ui.ar"),
    args_file="commandline.txt",
    notes=(
        "Open1560 also reads arguments from commandline.txt. The engine splices "
        "that file in before the real command line and the last occurrence wins, "
        "so options set here override it — except for flags marked negatable="
        "False, which the engine cannot switch back off."
    ),
    mod_spec=ModSpec(
        archive_suffixes=(".ar",),
        priority_prefix="!",
        # Community packs use very deep prefixes to force load order — the
        # Revisited V3 mouse fix ships with 43 of them.
        max_priority=64,
        priority_help=(
            "The engine loads .ar archives in name order, so a leading '!' makes "
            "a mod override the base game. More '!' means higher priority."
        ),
        notes=(
            "Mods are usually one or more .ar archives dropped next to the "
            "executable, sometimes with loose files under dev/."
        ),
        scan_staging=True,
        staging_help=(
            "Mods parked in these folders are indexed where they are, not "
            "copied, and only written into the game folder when enabled."
        ),
    ),
    options=(
        # --- Gameplay ---
        # These three are plain argv scans in mmcityinfo/state.cpp, not
        # cmd_param, so they can only be switched on.
        OptionSpec(
            "allcars", "Unlock all cars", "bool", False, "Gameplay",
            negatable=False,
        ),
        OptionSpec(
            "allrace", "Unlock all races", "bool", False, "Gameplay",
            negatable=False,
        ),
        OptionSpec(
            "nodamage", "Disable damage", "bool", False, "Gameplay",
            negatable=False,
        ),
        OptionSpec(
            "maxcops", "Max cops chasing", "int", 3, "Gameplay",
            help="Number of police units that can pursue you at once.",
            minimum=0, maximum=100,
        ),
        OptionSpec(
            "speedycops", "Vanilla cop speed boost", "bool", False, "Gameplay",
            help="Restores the original frame-rate-dependent cop speed boost.",
        ),
        OptionSpec(
            "speedrun", "Speedrun conditions", "bool", False, "Gameplay",
            help="Applies -nosmoothstep -maxfps 60 -speedycops.",
        ),
        # --- Video ---
        OptionSpec("window", "Windowed", "bool", False, "Video"),
        OptionSpec(
            "border", "Window border", "bool", True, "Video",
            help="Only applies in windowed mode.",
        ),
        # PARAM_width/PARAM_height override the resolution the game itself
        # picked (midtown.cpp: SetRes(PARAM_width.get_or(width), ...)), so 0
        # here means "leave the game's own choice alone".
        OptionSpec(
            "width", "Resolution width", "int", 0, "Video",
            help="0 keeps whatever resolution the game is set to.",
            minimum=0, maximum=7680,
        ),
        OptionSpec(
            "height", "Resolution height", "int", 0, "Video",
            help="Set both width and height, or neither.",
            minimum=0, maximum=4320,
        ),
        OptionSpec(
            "msaa", "Anti-aliasing", "choice", 0, "Video",
            choices=(("Off", 0), ("2x", 2), ("4x", 4), ("8x", 8)),
            help="Not available with legacy OpenGL or some integrated GPUs.",
        ),
        OptionSpec("vsync", "Vertical sync", "bool", True, "Video"),
        OptionSpec(
            "maxfps", "FPS limit", "int", 0, "Video",
            help="0 means unlimited.", minimum=0, maximum=1000,
        ),
        OptionSpec(
            "afilter", "Anisotropic filtering", "int", 16, "Video",
            minimum=1, maximum=16,
        ),
        OptionSpec(
            "scaling", "Scaling mode", "choice", 0, "Video",
            choices=(
                ("Stretched (keep aspect)", 0),
                ("Stretched", 1),
                ("Centered", 2),
                ("Centered (integer)", 3),
            ),
        ),
        OptionSpec(
            "legacygl", "Legacy OpenGL", "bool", False, "Video",
            help="Compatibility context. Try this if performance is poor.",
        ),
        OptionSpec(
            "nativeres", "Render at native resolution", "bool", True, "Video",
            help="Forced on when MSAA or legacy OpenGL is in use.",
        ),
        OptionSpec(
            "mirrordist", "Mirror draw distance", "int", 200, "Video",
            minimum=0, maximum=2000,
        ),
        OptionSpec("fovfix", "FOV scaling by resolution", "bool", True, "Video"),
        OptionSpec(
            "smoothstep", "Frame time smoothing", "bool", True, "Video",
            help="Reduces stutter between frames.",
        ),
        # --- Input ---
        OptionSpec(
            "mousemode", "Mouse mode", "choice", 0, "Input",
            choices=(
                ("Relative (raw input)", 0),
                ("Relative (warping)", 1),
                ("Absolute", 2),
            ),
            help="Try 1 or 2 if the cursor does not move correctly.",
        ),
        # --- Advanced ---
        OptionSpec(
            "heapsize", "Game heap (MB)", "int", 64, "Advanced",
            help="Large city or vehicle mods may need considerably more.",
            minimum=16, maximum=2048,
        ),
        OptionSpec("console", "Console logging", "bool", False, "Advanced"),
        OptionSpec(
            "cdid", "CD music with a virtual CD", "bool", False, "Advanced",
        ),
        OptionSpec(
            "prio", "Process priority", "int", 2, "Advanced",
            minimum=0, maximum=5,
        ),
        OptionSpec(
            "affinity", "Process affinity mask", "int", 0, "Advanced",
            help="0 leaves affinity untouched.", minimum=0, maximum=255,
        ),
        OptionSpec(
            "sync", "Disable multi-threading", "bool", True, "Advanced",
        ),
        OptionSpec(
            "cleandir", "Clean debug files on start", "bool", True, "Advanced",
        ),
        OptionSpec(
            "config", "Force graphics mode redetection", "bool", False, "Advanced",
        ),
    ),
)
