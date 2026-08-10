"""Midtown Madness 2 (2000).

Unlike MM1, this game is not configured on the command line. `midtown2.exe` is
a packed retail binary with no usable argument surface, and the community
configures the game through MM2Hook's `mm2hook.ini` instead — 104 documented
settings across nine sections. Every option below therefore carries an
`ini_section` and is written into that file, which the launcher edits in place
so the inline documentation survives.

Defaults below mirror the values MM2Hook ships with, so an untouched profile
leaves the file byte-for-byte alone.
"""

from __future__ import annotations

from .base import ExeTarget, GameDef, ModSpec, OptionSpec

_COLOURS = (
    ("White", -1), ("Black", 0), ("Red", 1), ("Blue", 2), ("Green", 3),
    ("Darker red", 4), ("Yellow", 5), ("Orange", 6), ("Purple", 7),
    ("Aqua", 8), ("Pink", 9), ("Lighter pink", 10),
)
_LIGHT_STYLE = (
    ("MM2 default", 0), ("MM1 style", 1), ("Both", 2), ("None", 3),
)
_HUD_STYLE = (
    ("MM2", 0), ("MM1", 1), ("NFS Hot Pursuit II", 2),
    ("NFS Most Wanted", 3), ("NFS Carbon", 4), ("Custom", 5),
)

MM2 = GameDef(
    id="mm2",
    title="Midtown Madness 2",
    subtitle="San Francisco and London, rain or shine",
    year="2000",
    developer="Angel Studios",
    publisher="Microsoft",
    released="September 2000",
    genre="Open-world arcade racing",
    setting="San Francisco and London",
    accent="#4A90D9",
    icon_shape="car",
    description=(
        "Midtown Madness 2 takes the first game's idea — a whole city, no "
        "invisible walls — and gives you two of them. San Francisco arrives "
        "with the hills and the trolleys, London with roundabouts, black cabs "
        "and traffic running the other way round.\n\n"
        "Alongside Blitz, Circuit and Checkpoint sits Crash Course, a set of "
        "scripted stunt-driving jobs that ask for precision rather than speed. "
        "Cruise is still there, still the mode people leave running. Weather "
        "and time of day are yours to pick, and both genuinely change the "
        "drive: wet cobbles in London are not the same road as dry ones.\n\n"
        "Its afterlife is the real story. MM2 has been modded continuously for "
        "two decades — new cars, whole new cities, and MM2Hook, which reaches "
        "into the retail binary to add features Angel Studios never shipped. "
        "Most of what the Options tab exposes here comes from that project."
    ),
    extra_facts=(
        ("Engine", "Angel Game Engine (AGE)"),
        ("Mod framework", "MM2Hook"),
    ),
    exe_targets=(
        ExeTarget(
            id="retail",
            label="Midtown Madness 2",
            filename="midtown2.exe",
            description=(
                "The game. If MM2Hook is installed it loads automatically "
                "through the dinput.dll shim next to the executable."
            ),
            recommended=True,
        ),
    ),
    # MM2HACK.exe sits in the same folder and is deliberately not offered as a
    # launch target: it is a separate tweaking utility, not the game, and this
    # pack's own README warns people off running it by mistake.
    signature_files=("midtown2.exe", "mm2core.ar"),
    data_files=("mm2core.ar", "mm2tex.ar", "mm2aud.ar"),
    options_file="mm2hook.ini",
    options_file_hint=(
        "These settings live in mm2hook.ini. That file is part of MM2Hook, "
        "which does not appear to be installed in this copy — install it and "
        "the settings below will apply."
    ),
    notes=(
        "MM2 is configured through MM2Hook's mm2hook.ini rather than the "
        "command line. The launcher edits that file in place, preserving its "
        "comments and formatting."
    ),
    mod_spec=ModSpec(
        archive_suffixes=(".ar",),
        priority_prefix="!",
        max_priority=64,
        priority_help=(
            "The engine loads .ar archives in name order, so a leading '!' "
            "makes a mod override the base game. More '!' means higher priority."
        ),
        notes=(
            "Mods are .ar archives dropped next to midtown2.exe. MM2Hook can "
            "also load loose files from a 'mods' folder when UseModsFolder is on."
        ),
        scan_staging=True,
        staging_help=(
            "Mods parked in these folders are indexed where they are, not "
            "copied, and only written into the game folder when enabled."
        ),
    ),
    options=(
        # --- Engine -----------------------------------------------------
        OptionSpec(
            "HeapSize", "Game heap (MB)", "int", 128, "Engine",
            ini_section="Game Settings", minimum=16, maximum=2048,
            help="Large city and vehicle mods need considerably more than the "
                 "32MB the game shipped with.",
        ),
        OptionSpec(
            "AudioHeapSize", "Audio heap (MB)", "int", 16, "Engine",
            ini_section="Game Settings", minimum=2, maximum=256,
        ),
        OptionSpec(
            "AudioMaxSounds", "Max sounds", "int", 6500, "Engine",
            ini_section="Game Settings", minimum=400, maximum=20000,
        ),
        OptionSpec(
            "DisableMutex", "Allow multiple instances", "bool", False, "Engine",
            ini_section="Game Settings",
            help="Lets more than one copy of the game run at once.",
        ),
        OptionSpec(
            "UseOldAutoDetect", "Old display auto-detection", "bool", False,
            "Engine", ini_section="Game Settings",
            help="Leaving this off speeds up loading.",
        ),
        OptionSpec(
            "MaxViewDistance", "Max view distance", "int", 1000, "Engine",
            ini_section="Game Settings", minimum=100, maximum=5000,
        ),
        # --- Gameplay ---------------------------------------------------
        OptionSpec(
            "MaximumCopsLimit", "Max cops pursuing", "int", 3, "Gameplay",
            ini_section="Features", minimum=0, maximum=32,
            help="0 means unlimited.",
        ),
        OptionSpec(
            "Ragdolls", "Pedestrian ragdolls", "bool", True, "Gameplay",
            ini_section="Features",
            help="Collision with pedestrians, with Midnight Club-style physics.",
        ),
        OptionSpec(
            "3DDamage", "3D damage", "bool", True, "Gameplay",
            ini_section="Features", help="On mods that support it.",
        ),
        OptionSpec(
            "DynamicParkedCarDensity", "Traffic slider controls parked cars",
            "bool", True, "Gameplay", ini_section="Features",
        ),
        OptionSpec(
            "OpponentsUseAllColors", "Opponents use all colours", "bool", False,
            "Gameplay", ini_section="Features",
        ),
        OptionSpec(
            "MM1StyleTransmission", "MM1-style transmission", "bool", False,
            "Gameplay", ini_section="Features",
            help="More realistic transmission behaviour.",
        ),
        OptionSpec(
            "MM1StyleAutoReverse", "MM1-style auto reverse", "bool", False,
            "Gameplay", ini_section="Features",
        ),
        OptionSpec(
            "PhysicalEngineDamage", "Damage affects engine", "bool", False,
            "Gameplay", ini_section="Features",
            help="A smoking engine loses torque and top speed.",
        ),
        OptionSpec(
            "EscapeDeepWater", "Let you escape deep water", "bool", True,
            "Gameplay", ini_section="Features",
        ),
        OptionSpec(
            "GTAStyleHornSiren", "Horn and siren on one button", "bool", True,
            "Gameplay", ini_section="Features",
            help="Tap to toggle the siren, hold for the horn.",
        ),
        # --- Graphics ---------------------------------------------------
        OptionSpec(
            "3DShadows", "3D shadows", "bool", False, "Graphics",
            ini_section="Features",
            help="On player, opponent and traffic vehicles, and props.",
        ),
        OptionSpec(
            "ReflectionsOnBreakables", "Reflections on breakables", "bool", True,
            "Graphics", ini_section="Features",
        ),
        OptionSpec(
            "ReflectionsOnCarParts", "Reflections on car parts", "bool", False,
            "Graphics", ini_section="Features",
            help="Addon cars that are not set up for this get shiny tyres.",
        ),
        OptionSpec(
            "MM1StyleDamage", "MM1-style damage textures", "bool", False,
            "Graphics", ini_section="Features",
        ),
        OptionSpec(
            "EnableSpinningWheels", "Blurred spinning wheels", "bool", True,
            "Graphics", ini_section="Experimental",
            help="Only on vehicles that support it.",
        ),
        OptionSpec(
            "MM1StyleReflections", "MM1-style reflections", "bool", False,
            "Graphics", ini_section="Experimental",
            help="Based on camera position rather than model rotation.",
        ),
        OptionSpec(
            "LensFlare", "Lens flare on police lights", "bool", False,
            "Graphics", ini_section="Experimental",
            help="Unused original effect. Somewhat buggy.",
        ),
        OptionSpec(
            "HeadlightStyle", "Headlight objects", "choice", 0, "Graphics",
            ini_section="Experimental", choices=_LIGHT_STYLE,
            help="MM1-style HLIGHT objects look wrong on most vanilla cars.",
        ),
        OptionSpec(
            "SirenStyle", "Siren objects", "choice", 0, "Graphics",
            ini_section="Experimental", choices=_LIGHT_STYLE,
        ),
        OptionSpec(
            "ModelVisibility", "Car body visible from inside", "bool", False,
            "Graphics", ini_section="Experimental",
            help="Many cars are not set up for this and look strange.",
        ),
        # --- Audio ------------------------------------------------------
        OptionSpec(
            "AmbientSoundsWithMusic", "Ambient sounds with music", "bool", True,
            "Audio", ini_section="Features",
        ),
        OptionSpec(
            "WaterSplashSound", "Water splash sound", "bool", True, "Audio",
            ini_section="Features",
        ),
        OptionSpec(
            "ExplosionSound", "Explosion sound", "bool", True, "Audio",
            ini_section="Features",
        ),
        # --- Interface --------------------------------------------------
        OptionSpec(
            "HudMapColorStyle", "Hud map style", "choice", 0, "Interface",
            ini_section="HudMap", choices=_HUD_STYLE,
            help="Colours below apply only with Custom selected.",
        ),
        OptionSpec(
            "PlayerTriColor", "Player marker", "choice", 5, "Interface",
            ini_section="HudMap", choices=_COLOURS,
        ),
        OptionSpec(
            "PoliceTriColor", "Police marker", "choice", 1, "Interface",
            ini_section="HudMap", choices=_COLOURS,
        ),
        OptionSpec(
            "OpponentTriColor", "Opponent marker", "choice", 7, "Interface",
            ini_section="HudMap", choices=_COLOURS,
        ),
        OptionSpec(
            "OpponentIconStyle", "Opponent icon style", "choice", 0, "Interface",
            ini_section="Icons", choices=_HUD_STYLE,
        ),
        OptionSpec(
            "EnableHudArrowStyles", "Alternative hud arrows", "bool", True,
            "Interface", ini_section="Features",
            help="Unused Blitz and Crash Course arrow styles.",
        ),
        OptionSpec(
            "EnableHeadBobbing", "Dashboard head bobbing", "bool", False,
            "Interface", ini_section="Dashboards",
            help="Experimental. You may see over the edge of some dashboards.",
        ),
        # --- Integration ------------------------------------------------
        OptionSpec(
            "UseModsFolder", "Load loose files from mods folder", "bool", True,
            "Integration", ini_section="Features",
            help="Files in a 'mods' folder override the contents of .ar archives.",
        ),
        OptionSpec(
            "EnableLua", "Lua scripting", "bool", True, "Integration",
            ini_section="Features", help="Always disabled in multiplayer.",
        ),
        OptionSpec(
            "UseRichPresence", "Discord rich presence", "bool", True,
            "Integration", ini_section="Features",
            help="Broadcasts your city, mode and vehicle to your Discord profile.",
        ),
        # --- Diagnostics ------------------------------------------------
        OptionSpec(
            "ShowConsole", "MM2Hook console", "bool", False, "Diagnostics",
            ini_section="Debug",
        ),
        OptionSpec(
            "DebugLog", "Debug logging", "bool", True, "Diagnostics",
            ini_section="Debug",
        ),
        OptionSpec(
            "DebugLogLevel", "Log level", "choice", 3, "Diagnostics",
            ini_section="Debug",
            choices=(("None", 0), ("Messages", 1), ("Warnings", 2), ("Errors", 3)),
        ),
        OptionSpec(
            "AGEDebug", "Verbose AGE logging", "bool", False, "Diagnostics",
            ini_section="Debug",
            help="Writes AGE.log. Known to destabilise multiplayer.",
        ),
    ),
)
