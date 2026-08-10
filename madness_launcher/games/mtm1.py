"""Monster Truck Madness (1996).

A different engine to the Midtown games, and it shows in both places the
launcher touches.

Archives are `.POD` (Terminal Reality's format), and load order is not encoded
in filenames — `MONSTER.EXE` reads `pod.ini`, a counted list of archive paths.
Enabling a mod adds a line there rather than renaming anything, and since the
paths are relative to the game folder, a POD already sitting in the game is
referenced where it is.

Settings live in `System/MONSTER.INI`. Options below are limited to keys whose
meaning is unambiguous from the shipped file; the many `*Flag` keys that hold
values other than 0/1 are exposed as plain numbers rather than invented labels.
"""

from __future__ import annotations

from .base import ExeTarget, GameDef, ModSpec, OptionSpec, PathSetting

MTM1 = GameDef(
    id="mtm1",
    title="Monster Truck Madness",
    subtitle="Twelve tons, no subtlety",
    year="1996",
    developer="Terminal Reality",
    publisher="Microsoft",
    released="1996",
    genre="Off-road racing",
    setting="American dirt circuits",
    accent="#6FAE3F",
    icon_shape="truck",
    description=(
        "Monster Truck Madness is what happens when a racing game stops "
        "pretending its cars are delicate. You get eleven thousand pounds of "
        "truck on a suspension that never quite settles, and courses built out "
        "of hills, water and things to land badly on.\n\n"
        "The circuits mix drag races, rallies and full off-road tournaments, "
        "and the physics is the joke and the point at once: a truck that lands "
        "nose-down at speed will happily cartwheel the length of the track "
        "while Army Armstrong keeps commentating over the top of it.\n\n"
        "It was also unusually open for 1996. Terminal Reality shipped a track "
        "editor, and the community has been making .POD files for it ever "
        "since — new trucks, new circuits, new paint. The launcher reads the "
        "same pod.ini the game does, so anything already in your folder can be "
        "switched on without moving a file."
    ),
    extra_facts=(
        ("Archives", ".POD"),
        ("Load order", "pod.ini"),
    ),
    exe_targets=(
        ExeTarget(
            id="retail",
            label="Monster Truck Madness",
            filename="MONSTER.EXE",
            description="The 1996 executable. Usually wants a compatibility mode.",
            recommended=True,
        ),
    ),
    signature_files=("MONSTER.EXE", "MONSTER.CNT"),
    # The core archives live under System/, not beside the executable.
    data_files=("System/GAME.POD", "System/UI.POD", "System/TRUCK.POD"),
    needs_single_core=True,
    single_core_reason=(
        "Monster Truck Madness times its physics against a millisecond clock. "
        "On a modern CPU a frame takes less than that, the delta rounds to "
        "zero, and the truck will not move off the start line. The launcher "
        "pins it to one core at launch."
    ),
    hook_dll="mtmhook.dll",
    injector="mtminject.exe",
    hook_name="mtmhook",
    options_file="System/MONSTER.INI",
    # Written as absolute paths by the 1996 installer, so they break the moment
    # the folder is moved — which is how most copies of this game arrive.
    path_settings=(
        PathSetting("CD-ROM", "CDROMPath", "", "Game data path"),
        PathSetting("CD-ROM", "helpFileName", "MONSTER.HLP", "Help file"),
    ),
    options_file_hint=(
        "These settings live in System/MONSTER.INI, which was not found in this "
        "copy. The game writes it on first run."
    ),
    notes=(
        "Monster Truck Madness keeps its load order in pod.ini and its settings "
        "in System/MONSTER.INI. The launcher edits both in place.\n\n"
        "There is no widescreen mode: MONSTER.EXE hardcodes three resolutions "
        "and the cockpit is pre-rendered art per screen height.\n\n"
        "Scale it with your GPU driver, not with dgVoodoo. This game is an "
        "8-bit palettised software renderer that writes straight into a "
        "DirectDraw surface, and dgVoodoo renders it as a blank grey screen. "
        "It is built for hardware Glide and Direct3D, which is not this."
    ),
    mod_spec=ModSpec(
        archive_suffixes=(".pod",),
        # No filename prefix convention here: pod.ini decides the order.
        priority_prefix="",
        max_priority=0,
        notes=(
            "Mods are .POD archives — trucks, tracks and paint jobs. The game "
            "loads whatever pod.ini lists, in the order it lists them."
        ),
        scan_staging=True,
        staging_help=(
            "PODs found in the game's subfolders are listed where they are. "
            "Enabling one adds it to pod.ini; nothing is copied or renamed."
        ),
        order_file="pod.ini",
        order_help=(
            "pod.ini is the game's own load-order list. Entries later in the "
            "list load after earlier ones."
        ),
    ),
    options=(
        # --- Display ----------------------------------------------------
        # The cockpit is pre-rendered artwork stored per screen height —
        # ART\PBIG200/400/480.RAW and their B/L/R views, in TRUCK.POD. There is
        # no art for any other height, so setting one the game has no cockpit
        # for makes it fail on load with "Unable to open cockpit file".
        OptionSpec(
            "gamePIXX", "Resolution width", "choice", 640, "Display",
            ini_section="Graphics",
            choices=(("320", 320), ("640", 640)),
            valid_values=(320, 640),
        ),
        OptionSpec(
            "gamePIXY", "Resolution height", "choice", 480, "Display",
            ini_section="Graphics",
            choices=(("200", 200), ("400", 400), ("480", 480)),
            valid_values=(200, 400, 480),
            help=(
                "The engine has only three modes: 320x200, 320x400 and 640x480. "
                "To fill a widescreen display, set your GPU driver's scaling to "
                "full-panel rather than aspect-preserving. Do not use a "
                "DirectDraw wrapper here - see the note below."
            ),
            invalid_help=(
                "Stock, the game fails on load here with \"Unable to open "
                "cockpit file\" — it looks for a cockpit named after the screen "
                "height. mtmhook's CockpitAnyResolution patch gets past that, "
                "but the cockpit is still drawn at 640x480 and the field of "
                "view is not corrected, so the view is stretched rather than "
                "wider. Use 200, 400 or 480 for a supported setup."
            ),
        ),
        OptionSpec(
            "autoFullScreen", "Start full screen", "bool", True, "Display",
            ini_section="Graphics",
        ),
        OptionSpec(
            "useDirect3D", "Use Direct3D", "bool", False, "Display",
            ini_section="Graphics",
            help="Off uses the software renderer, which is the safer choice on "
                 "modern machines.",
        ),
        OptionSpec(
            "aspectRatio", "Correct aspect ratio", "bool", True, "Display",
            ini_section="Graphics",
        ),
        # --- Graphics quality -------------------------------------------
        OptionSpec(
            "skyTextureFlag", "Sky textures", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "filterFlag", "Texture filtering", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "ditherFlag", "Dithering", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "blendFlag", "Blending", "bool", False, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "antialiasFlag", "Anti-aliasing", "bool", False, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "flatShadeFlag", "Flat shading", "bool", False, "Graphics",
            ini_section="Graphics", help="Faster, and much uglier.",
        ),
        OptionSpec(
            "useZFlag", "Z-buffer", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "autoQuality", "Adjust quality automatically", "bool", True,
            "Graphics", ini_section="Graphics",
            help="Drops detail to hold the minimum frame rate below.",
        ),
        OptionSpec(
            "autoMinFrameRate", "Minimum frame rate", "int", 8, "Graphics",
            ini_section="Graphics", minimum=1, maximum=60,
        ),
        # These hold values beyond 0/1 in the shipped file, and the engine does
        # not document what each level means — so they stay as numbers.
        OptionSpec(
            "textureResolution", "Texture resolution level", "int", 1, "Graphics",
            ini_section="Graphics", minimum=0, maximum=3,
            help="Higher is sharper. The game writes 1 by default.",
        ),
        OptionSpec(
            "perspectiveFlag", "Perspective correction level", "int", 2,
            "Graphics", ini_section="Graphics", minimum=0, maximum=2,
        ),
        OptionSpec(
            "airShadowFlag", "Shadow detail level", "int", 2, "Graphics",
            ini_section="Graphics", minimum=0, maximum=2,
        ),
        OptionSpec(
            "maxD3DTextures", "Max Direct3D textures", "int", 240, "Graphics",
            ini_section="Graphics", minimum=16, maximum=2048,
        ),
        # --- Audio ------------------------------------------------------
        OptionSpec(
            "soundFlag", "Sound effects", "bool", True, "Audio",
            ini_section="Sound",
        ),
        OptionSpec(
            "musicFlag", "Music", "bool", True, "Audio", ini_section="Sound",
        ),
        OptionSpec(
            "stereoFlag", "Stereo", "bool", False, "Audio", ini_section="Sound",
        ),
        OptionSpec(
            "redbookFlag", "CD audio", "bool", False, "Audio",
            ini_section="Sound", help="Requires the original disc in the drive.",
        ),
        OptionSpec(
            "mixSpeed", "Mixing rate", "choice", 11025, "Audio",
            ini_section="Sound",
            choices=(("11 kHz", 11025), ("22 kHz", 22050), ("44 kHz", 44100)),
        ),
        OptionSpec(
            "soundVolume", "Sound volume", "int", 13108, "Audio",
            ini_section="Sound", minimum=0, maximum=65535,
        ),
        OptionSpec(
            "musicVolume", "Music volume", "int", 13108, "Audio",
            ini_section="Sound", minimum=0, maximum=65535,
        ),
        # --- Game -------------------------------------------------------
        OptionSpec(
            "difficulty", "Difficulty", "int", 1, "Game",
            ini_section="Game", minimum=0, maximum=2,
        ),
        OptionSpec(
            "defaultOpponents", "Default opponents", "int", 7, "Game",
            ini_section="Game", minimum=0, maximum=11,
        ),
        OptionSpec(
            "autoShift", "Automatic gearbox", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "briefingFlag", "Show race briefings", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "showDemoFlag", "Attract-mode demo", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "detailLevel", "World detail level", "int", 2, "Game",
            ini_section="Game", minimum=0, maximum=2,
        ),
        OptionSpec(
            "partsFlag", "Flying parts level", "int", 2, "Game",
            ini_section="Game", minimum=0, maximum=2,
        ),
        OptionSpec(
            "cinemaFlag", "Cinematics level", "int", 3, "Game",
            ini_section="Game", minimum=0, maximum=3,
        ),
        OptionSpec(
            "commentaryFlag", "Commentary level", "int", 2, "Game",
            ini_section="Game", minimum=0, maximum=2,
            help="Army Armstrong's running commentary.",
        ),
        # --- Input ------------------------------------------------------
        OptionSpec(
            "joystickActive", "Joystick", "bool", False, "Input",
            ini_section="Control",
        ),
        OptionSpec(
            "showQuickHelpFlag", "Quick help", "bool", False, "Input",
            ini_section="Help",
        ),
    ),
)
