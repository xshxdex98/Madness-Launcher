"""Checks for executable icon extraction and the painted fallbacks."""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="madness-icons-"))

# The real config is read directly rather than through Config.load() with the
# data folder redirected: extraction is the part worth testing, and it can only
# be tested against real installs. Nothing here writes — exeicon and gameart
# only read executables and paint into memory.
def _real_installs() -> dict[str, str]:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    config = Path(base) / "MadnessLauncher" / "config.json"
    if not config.is_file():
        return {}
    try:
        raw = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    installs = raw.get("installs") or {}
    return {
        key: value.get("path", "")
        for key, value in installs.items()
        if isinstance(value, dict)
    }

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from madness_launcher import exeicon  # noqa: E402
from madness_launcher.games.registry import GAMES  # noqa: E402
from madness_launcher.ui import gameart  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)

print("malformed input is refused, not fatal")
junk = SANDBOX / "junk.exe"
junk.write_bytes(b"not an executable at all")
check("garbage file returns None", exeicon.extract_ico(junk) is None)

empty = SANDBOX / "empty.exe"
empty.write_bytes(b"")
check("empty file returns None", exeicon.extract_ico(empty) is None)

stub = SANDBOX / "stub.exe"
stub.write_bytes(b"MZ" + b"\0" * 0x3A + struct.pack("<I", 0x400) + b"\0" * 32)
check("truncated PE returns None", exeicon.extract_ico(stub) is None)

missing = SANDBOX / "nope.exe"
check("absent file returns None", exeicon.extract_ico(missing) is None)

# A real PE with no resource directory at all: Python's own launcher will do if
# it has none, but the point is only that a valid PE never raises.
check(
    "a real PE never raises",
    exeicon.extract_ico(Path(sys.executable)) is not None
    or exeicon.extract_ico(Path(sys.executable)) is None,
)

print("\nextraction from the configured games")
installs = _real_installs()
extracted = 0
configured = 0
for game in GAMES:
    path = installs.get(game.id, "")
    root = Path(path) if path else None
    if root is None or not root.is_dir():
        print(f"  --    {game.id}: not set up, skipped")
        continue
    configured += 1
    icon = gameart.icon_for(game, root)
    if icon is None:
        print(f"  --    {game.id}: no icon in any executable")
        continue
    extracted += 1
    sizes = sorted(s.width() for s in icon.availableSizes())
    check(f"{game.id}: icon decodes at usable sizes", bool(sizes), str(sizes))
    check(
        f"{game.id}: 18px mark is not blank",
        not icon.pixmap(QSize(18, 18)).isNull(),
    )
check("found installs to test against", configured > 0, f"{configured} configured")
if configured:
    check(
        "most configured games yield an icon",
        extracted >= configured - 1,
        f"{extracted}/{configured}",
    )

print("\nan explicit icon_exe is honoured")
mcm2 = next((g for g in GAMES if g.id == "mcm2"), None)
if mcm2 is not None:
    check(
        "mcm2 names the game binary, not the launcher wrapper",
        mcm2.icon_exe.lower() == "mcm2.exe",
        mcm2.icon_exe,
    )
    check(
        "the named binary is not the first exe target",
        not mcm2.exe_targets or mcm2.exe_targets[0].filename.lower() != "mcm2.exe",
        mcm2.exe_targets[0].filename if mcm2.exe_targets else "-",
    )

print("\npainted fallbacks")
shapes = {g.id: g.icon_shape for g in GAMES}
check(
    "every game declares a silhouette",
    all(s in ("car", "truck", "bike") for s in shapes.values()),
    str(shapes),
)
check("families differ", len(set(shapes.values())) == 3, str(set(shapes.values())))

for game in GAMES:
    pixmap = gameart.painted_mark(game, 18)
    image = pixmap.toImage()
    ink = sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 30
    )
    check(f"{game.id}: silhouette has ink", ink > 60, f"{ink}px")

# Distinct shapes must not paint identical images, or the fallback is useless.
renders = {}
for game in GAMES:
    renders.setdefault(game.icon_shape, gameart.painted_mark(game, 18).toImage())
check(
    "the three silhouettes are actually different",
    len({r.constBits().tobytes() for r in renders.values()}) == 3,
)

print("\nfallback when there is no executable")
gameart.clear_cache()
for game in GAMES:
    check(
        f"{game.id}: unconfigured game still gets a mark",
        not gameart.mark(game, None, 18).isNull(),
    )
gameart.clear_cache()

print("\nnavigation glyphs")
glyphs = {}
for name in ("library", "chat", "settings"):
    pixmap = gameart.nav_glyph(name, 18)
    check(f"{name} glyph paints", not pixmap.isNull())
    image = pixmap.toImage()
    ink = sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 30
    )
    check(f"{name} glyph has ink", ink > 40, f"{ink}px")
    glyphs[name] = image.constBits().tobytes()
check("the three glyphs are different", len(set(glyphs.values())) == 3)
check(
    "an unknown glyph name is blank rather than an error",
    gameart.nav_glyph("nonsense", 18).toImage().constBits().tobytes()
    not in set(glyphs.values()),
)

print("\ncaching")
gameart.clear_cache()
first = gameart.icon_for(GAMES[0], None)
second = gameart.icon_for(GAMES[0], None)
check("a failed lookup is remembered", first is None and second is None)
check("the cache holds the entry", GAMES[0].id in gameart._cache)
gameart.clear_cache()
check("clearing empties it", GAMES[0].id not in gameart._cache)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all icon checks passed")
