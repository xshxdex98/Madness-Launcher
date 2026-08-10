"""Monster Truck Madness 2 (1998).

Same engine family as MTM1 — `.POD` archives and a `pod.ini` load-order list —
but two important differences:

* It is a Direct3D game, not a software renderer. There is no per-height cockpit
  artwork and therefore no resolution ceiling; this copy runs at 1920x1080.
* `pod.ini` lists archives in the game folder itself rather than under `system\\`,
  and the community ships tracks as loose `.pod` files dropped in beside the
  game. A stock-ish install has dozens of them.

Settings live in `system/Monster.INI`. Its `[Sound]` section stores words rather
than numbers (`YEP`, `STEREO`), which is why those options are choices with
string values rather than checkboxes.

Defaults below are taken from a working install. As with MTM1, the game rewrites
this file as you play, so they are a sane reset target rather than verified
factory values.
"""

from __future__ import annotations

from .base import ExeTarget, GameDef, ModSpec, OptionSpec

_OFF_ON = (("Off", 0), ("On", 1))
_YEP = (("Yes", "YEP"), ("No", "NOPE"))

MTM2 = GameDef(
    id="mtm2",
    title="Monster Truck Madness 2",
    subtitle="Bigger trucks, worse weather",
    year="1998",
    developer="Terminal Reality",
    publisher="Microsoft",
    released="1998",
    genre="Off-road racing",
    setting="Circuits, quarries and back roads",
    accent="#C7622E",
    icon_shape="truck",
    description=(
        "Monster Truck Madness 2 keeps everything absurd about the first game "
        "and gives it hardware acceleration, weather, and a much longer list of "
        "places to land badly. Rain and snow are not just a filter over the "
        "camera — a wet quarry is a genuinely different drive from a dry one.\n\n"
        "It kept the things that made the original worth loading: Army "
        "Armstrong still commentating over your mistakes, physics still happy "
        "to send eleven thousand pounds of truck end over end, and circuits "
        "built for jumping rather than cornering.\n\n"
        "Its long afterlife is community-made. Terminal Reality's track editor "
        "meant people never stopped building, and a well-fed install carries "
        "dozens of custom tracks as loose .pod files. The launcher reads the "
        "same pod.ini the game does, so everything already in your folder shows "
        "up with the right things ticked."
    ),
    extra_facts=(
        ("Archives", ".POD"),
        ("Load order", "pod.ini"),
        ("Renderer", "Direct3D"),
    ),
    exe_targets=(
        ExeTarget(
            id="retail",
            label="Monster Truck Madness 2",
            filename="monster.exe",
            description="The 1998 executable. Direct3D, so a wrapper such as "
                        "dgVoodoo is usually worth having.",
            recommended=True,
        ),
    ),
    # MAIN.POD is the discriminator: MTM1 also ships a monster.exe, so matching
    # on the executable alone would make the two games indistinguishable.
    signature_files=("MAIN.POD", "monster.exe"),
    # The engine archives. Listing them here both validates the install and
    # keeps them out of the mod list, where they would invite someone to
    # "disable" the game itself.
    data_files=(
        "MAIN.POD", "ui.pod", "truck2.pod", "startup.pod",
        "cockpit.pod", "sound.pod", "music.pod",
    ),
    options_file="system/Monster.INI",
    options_file_hint=(
        "These settings live in system/Monster.INI, which was not found in this "
        "copy. The game writes it on first run."
    ),
    notes=(
        "Monster Truck Madness 2 keeps its load order in pod.ini and its "
        "settings in system/Monster.INI. The launcher edits both in place.\n\n"
        "Unlike the first game this one renders through Direct3D, so any "
        "resolution the card supports works and a wrapper like dgVoodoo is a "
        "reasonable thing to run it under."
    ),
    mod_spec=ModSpec(
        archive_suffixes=(".pod",),
        priority_prefix="",
        max_priority=0,
        notes=(
            "Tracks and trucks are .pod archives sitting beside the game. The "
            "engine loads whatever pod.ini lists, in the order it lists them."
        ),
        scan_staging=True,
        staging_help=(
            "PODs are listed where they already are. Enabling one adds it to "
            "pod.ini; nothing is copied or renamed."
        ),
        order_file="pod.ini",
        order_help=(
            "pod.ini is the game's own load-order list. Entries later in the "
            "list load after earlier ones."
        ),
    ),
    options=(
        # --- Display ----------------------------------------------------
        OptionSpec(
            "gamePIXX", "Resolution width", "int", 1920, "Display",
            ini_section="Graphics", minimum=320, maximum=7680,
            help="Direct3D, so anything your card supports is fair game.",
        ),
        OptionSpec(
            "gamePIXY", "Resolution height", "int", 1080, "Display",
            ini_section="Graphics", minimum=200, maximum=4320,
        ),
        OptionSpec(
            "autoFullScreen", "Start full screen", "bool", True, "Display",
            ini_section="Graphics",
        ),
        OptionSpec(
            "useDirect3D", "Use Direct3D", "bool", True, "Display",
            ini_section="Graphics",
            help="Off falls back to the software renderer, which is far slower.",
        ),
        OptionSpec(
            "syncRetrace", "Vertical sync", "bool", True, "Display",
            ini_section="Graphics",
        ),
        OptionSpec(
            "aspectRatio", "Correct aspect ratio", "bool", True, "Display",
            ini_section="Graphics",
        ),
        # --- Graphics ---------------------------------------------------
        OptionSpec(
            "textureResolution", "Texture resolution level", "int", 1, "Graphics",
            ini_section="Graphics", minimum=0, maximum=3,
        ),
        OptionSpec(
            "maxD3DTextures", "Max Direct3D textures", "int", 2048, "Graphics",
            ini_section="Graphics", minimum=64, maximum=8192,
        ),
        OptionSpec(
            "filterFlag", "Texture filtering", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "antialiasFlag", "Anti-aliasing", "bool", False, "Graphics",
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
            "skyTextureFlag", "Sky textures", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "useZFlag", "Z-buffer", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "useAGPFlag", "Use AGP memory", "bool", True, "Graphics",
            ini_section="Graphics",
        ),
        OptionSpec(
            "autoQuality", "Adjust quality automatically", "bool", False,
            "Graphics", ini_section="Graphics",
            help="On, the game quietly drops detail to hold the frame rate "
                 "below. Off keeps whatever you set.",
        ),
        OptionSpec(
            "autoMinFrameRate", "Minimum frame rate", "int", 8, "Graphics",
            ini_section="Graphics", minimum=1, maximum=120,
        ),
        OptionSpec(
            "perspectiveFlag", "Perspective correction level", "int", 2,
            "Graphics", ini_section="Graphics", minimum=0, maximum=2,
        ),
        OptionSpec(
            "airShadowFlag", "Shadow detail level", "int", 1, "Graphics",
            ini_section="Graphics", minimum=0, maximum=2,
        ),
        # --- Game -------------------------------------------------------
        OptionSpec(
            "difficulty", "Difficulty", "int", 1, "Game",
            ini_section="Game", minimum=0, maximum=2,
        ),
        OptionSpec(
            "defaultOpponents", "Default opponents", "int", 0, "Game",
            ini_section="Game", minimum=0, maximum=11,
        ),
        OptionSpec(
            "detailLevel", "World detail level", "int", 2, "Game",
            ini_section="Game", minimum=0, maximum=2,
        ),
        OptionSpec(
            "weather", "Weather", "int", 0, "Game",
            ini_section="Game", minimum=0, maximum=3,
            help="Rain and snow change grip, not just the view.",
        ),
        OptionSpec(
            "autoShift", "Automatic gearbox", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "allowCrashDamage", "Crash damage", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "smokeEffectFlag", "Smoke effects", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "tireTrackFlag", "Tyre tracks", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "partsFlag", "Flying parts level", "int", 1, "Game",
            ini_section="Game", minimum=0, maximum=2,
        ),
        OptionSpec(
            "viewCockpit", "Cockpit view", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "showHiddenTrack", "Show hidden track", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "briefingFlag", "Show race briefings", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "commentaryFlag", "Spoken commentary", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "textCommentaryFlag", "Text commentary", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "kookyHornFlag", "Novelty horn", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "showInfoOverlay", "Info overlay", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "dontShowStartScreen", "Skip the start screen", "bool", True, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "showDemoFlag", "Attract-mode demo", "bool", False, "Game",
            ini_section="Game",
        ),
        OptionSpec(
            "cinemaFlag", "Cinematics", "int", 0, "Game",
            ini_section="Game", minimum=0, maximum=3,
        ),
        # --- Audio ------------------------------------------------------
        # This section stores words, not numbers, so these are choices whose
        # values are the strings the game itself writes.
        OptionSpec(
            "OutRate", "Mixing rate", "choice", 44100, "Audio",
            ini_section="Sound",
            choices=(("22 kHz", 22050), ("44 kHz", 44100), ("48 kHz", 48000)),
        ),
        OptionSpec(
            "OutBits", "Sample depth", "choice", 16, "Audio",
            ini_section="Sound", choices=(("8-bit", 8), ("16-bit", 16)),
        ),
        OptionSpec(
            "SpeakerCfg", "Speakers", "choice", "STEREO", "Audio",
            ini_section="Sound",
            choices=(("Mono", "MONO"), ("Stereo", "STEREO"),
                     ("Surround", "SURROUND")),
        ),
        OptionSpec(
            "UseModMusic", "Music", "choice", "YEP", "Audio",
            ini_section="Sound", choices=_YEP,
        ),
        OptionSpec(
            "UseRedBook", "CD audio", "choice", "YEP", "Audio",
            ini_section="Sound", choices=_YEP,
            help="Requires the original disc in the drive.",
        ),
        OptionSpec(
            "SfxVol", "Effects volume", "int", 7, "Audio",
            ini_section="Sound", minimum=0, maximum=10,
        ),
        OptionSpec(
            "ModGameMusicVol", "Music volume", "int", 10, "Audio",
            ini_section="Sound", minimum=0, maximum=10,
        ),
        OptionSpec(
            "MasterLVol", "Master volume (left)", "int", 100, "Audio",
            ini_section="Sound", minimum=0, maximum=100,
        ),
        OptionSpec(
            "MasterRVol", "Master volume (right)", "int", 100, "Audio",
            ini_section="Sound", minimum=0, maximum=100,
        ),
        # --- Multiplayer ------------------------------------------------
        OptionSpec(
            "Port", "Network port", "int", 2300, "Multiplayer",
            ini_section="Network", minimum=1, maximum=65535,
        ),
        OptionSpec(
            "networkChatFlag", "Show chat", "bool", True, "Multiplayer",
            ini_section="Game",
        ),
        OptionSpec(
            "networkChatSeconds", "Chat display seconds", "int", 5,
            "Multiplayer", ini_section="Game", minimum=1, maximum=60,
        ),
        OptionSpec(
            "latencyDisplay", "Latency display", "int", 2, "Multiplayer",
            ini_section="Game", minimum=0, maximum=3,
        ),
    ),
)
