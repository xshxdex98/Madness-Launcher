"""Checks for the Motocross Madness 2 record reader.

Builds its own .hs1 and .prf files rather than reading anyone's install, so
this runs anywhere and cannot touch a real game folder.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SANDBOX = Path(tempfile.mkdtemp(prefix="madness-mcm2-"))
os.environ["MADNESS_LAUNCHER_HOME"] = str(SANDBOX)

from madness_launcher.records import motocross as mc  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


EMPTY = struct.pack("<I", 0x7F7FFFFF)


def make_hs1(entries: list[tuple[str, float]], kind: int = 2) -> bytes:
    """A table in the game's own shape: header, then ten name+time slots."""
    out = struct.pack("<2I", kind, len(entries))
    for i in range(mc.SLOTS):
        if i < len(entries):
            name, seconds = entries[i]
            out += name.encode("latin-1").ljust(mc.NAME_BYTES, b"\0")[: mc.NAME_BYTES]
            out += struct.pack("<f", seconds)
        else:
            # Junk in the name of an empty slot, which is what the real files
            # carry — uninitialised memory, differing between files.
            out += bytes((i * 7 + 3) & 0xFF for _ in range(mc.NAME_BYTES)) + EMPTY
    return out


def install(tracks: dict[str, list[tuple[str, float]]], sizes=None) -> Path:
    root = SANDBOX / f"game{len(list(SANDBOX.iterdir()))}"
    for key, entries in tracks.items():
        folder, stem = key.split("/")
        d = root / "TERAFORM" / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.hs1").write_bytes(make_hs1(entries))
        size = (sizes or {}).get(stem)
        if size is None:
            size = mc.STOCK_TRACKS.get(stem.lower(), ("", 4096))[1] or 4096
        (d / f"{stem}.env").write_bytes(b"FAOE!" + b"\0" * max(size - 5, 0))
    return root


print("the shipped track list")
check("fifty-one stock tracks", len(mc.STOCK_TRACKS) == 51, str(len(mc.STOCK_TRACKS)))
counts: dict[str, int] = {}
for folder, _ in mc.STOCK_TRACKS.values():
    counts[folder] = counts.get(folder, 0) + 1
check(
    "split across the six disciplines as the game ships them",
    counts == {"BAJA": 5, "ENDURO": 5, "NATIONAL": 16, "QUARRIES": 5, "SX": 17, "TAG": 3},
    str(counts),
)
check("every stock entry has a size to check against",
      all(size > 0 for _, size in mc.STOCK_TRACKS.values()))
check("every discipline folder has a label", set(mc.DISCIPLINES) >= set(counts))

print("\nvanilla tracks and modded tracks")
check("a stock track at its right size", mc.classify("NAT05", "NATIONAL", 6780832) == mc.BOARD_VANILLA)
check("a stock name at the wrong size is not stock",
      mc.classify("NAT05", "NATIONAL", 999) == mc.BOARD_MODDED,
      "a community track dropped in as NAT05.env would inherit stock standing")
check("a stock name in the wrong discipline is not stock",
      mc.classify("NAT05", "SX", 6780832) == mc.BOARD_MODDED)
check("an unknown track is modded", mc.classify("Nut_Buster", "NATIONAL", 8243494) == mc.BOARD_MODDED)
check("case does not matter", mc.classify("nat05", "national", 6780832) == mc.BOARD_VANILLA)
check("no size given still passes on the name",
      mc.classify("NAT05", "NATIONAL", 0) == mc.BOARD_VANILLA)

print("\ntrack names")
check("underscores become spaces", mc.pretty_track("TD_Making_Tracks") == "TD Making Tracks")
check("a plain name is left alone", mc.pretty_track("5thGear") == "5thGear")
check("an empty name does not vanish", mc.pretty_track("") == "")

print("\ntrack index is the same on every machine")
check("derived from the name only", mc.track_index("NAT05") == mc.track_index("nat05"))
check("surrounding space does not change it", mc.track_index(" NAT05 ") == mc.track_index("NAT05"))
check("different tracks differ", mc.track_index("NAT05") != mc.track_index("NAT06"))
check("fits in a JSON-safe integer", 0 <= mc.track_index("NAT05") < 2**28)
idx = {mc.track_index(f"track{i}") for i in range(5000)}
check("no collisions across five thousand names", len(idx) == 5000, str(5000 - len(idx)))

print("\nreading a table")
root = install({"NATIONAL/NAT05": [("xSHXDEx", 59.9354), ("Rival", 61.5)]})
rows = mc.parse(root / "TERAFORM/NATIONAL/NAT05.hs1")
check("both entries read", len(rows) == 2, str(len(rows)))
check("the name comes back", rows[0].driver == "xSHXDEx", rows[0].driver)
check("the time is quantised at parse", rows[0].seconds == 59.935, str(rows[0].seconds))
check("empty slots are skipped", all(r.seconds < 1000 for r in rows))
check("the discipline comes from the folder", rows[0].kind == "Nationals", rows[0].kind)
check("a stock track lands on the vanilla board", rows[0].board == mc.BOARD_VANILLA)
check("times format as laps", rows[0].formatted == "59.935", rows[0].formatted)
check("over a minute formats with the minute",
      mc.MotoRecord("t", "SX", "d", 76.82).formatted == "1:16.820")

check("a missing file is not a crash", mc.parse(root / "nope.hs1") == [])
# Kept out of the install above: writing a broken table in before the
# snapshot would only prove the test wrong, which is what it did.
broken = SANDBOX / "broken"
broken.mkdir(exist_ok=True)
(broken / "short.hs1").write_bytes(b"\x02\x00\x00\x00")
check("a truncated file is not a crash", mc.parse(broken / "short.hs1") == [])
(broken / "nocount.hs1").write_bytes(struct.pack("<2I", 2, 0) + b"\0" * 200)
check("a table claiming no entries yields none", mc.parse(broken / "nocount.hs1") == [])
(broken / "wild.hs1").write_bytes(struct.pack("<2I", 2, 9999) + b"\0" * 200)
check("a nonsense count is refused outright", mc.parse(broken / "wild.hs1") == [])
faked = 0
for _ in range(400):
    (broken / "junk.hs1").write_bytes(os.urandom(208))
    if mc.parse(broken / "junk.hs1"):
        faked += 1
check(
    "random bytes do not become records",
    faked == 0,
    f"{faked}/400 random blobs parsed as a time — reading all ten slots "
    "regardless of the header count did this 96% of the time",
)
# The count is what makes that work, so prove it is actually being used.
padded = struct.pack("<2I", 2, 1)
padded += b"Real".ljust(mc.NAME_BYTES, b"\0") + struct.pack("<f", 42.5)
padded += (b"Ghost".ljust(mc.NAME_BYTES, b"\0") + struct.pack("<f", 43.5)) * 9
(broken / "over.hs1").write_bytes(padded)
rows = mc.parse(broken / "over.hs1")
check(
    "slots past the stated count are left alone",
    len(rows) == 1 and rows[0].driver == "Real",
    f"{[(r.driver, r.seconds) for r in rows]}",
)

print("\nwhat counts as a new record")
before = mc.snapshot(root)
check("the snapshot sees both", len(before) == 2, str(len(before)))
check("nothing new against itself", mc.improvements(before, before) == [])

# The real shape of the bug this guards: a faster time arrives at the top and
# pushes every existing entry down a slot.
root2 = install({"NATIONAL/NAT05": [("xSHXDEx", 55.0), ("xSHXDEx", 59.9354), ("Rival", 61.5)]})
after = mc.snapshot(root2)
gained = mc.improvements(before, after)
check(
    "a faster time that shifts the others reports only itself",
    len(gained) == 1 and gained[0].seconds == 55.0,
    f"{[(g.driver, g.seconds) for g in gained]} — comparing by slot would report all three",
)
check("and it knows its track", gained[0].track == "NAT05" and gained[0].board == mc.BOARD_VANILLA)
check("the other way round loses nothing", mc.improvements(after, before) == [])

print("\nnames learned from the rider profile")
prof = root / "UI" / "PROFILE" / "xSHXDEx"
prof.mkdir(parents=True, exist_ok=True)
blob = bytearray(b"\0" * 4760)
blob[0:7] = b"xSHXDEx"
wanted = ["Beaver County Race 01", "TD Making Tracks", "Arena Tag 02"]
for i, name in enumerate(wanted):
    at = mc.PROFILE_FIRST + i * mc.PROFILE_RECORD + mc.PROFILE_NAME_AT
    blob[at : at + len(name)] = name.encode()
(prof / "xSHXDEx.prf").write_bytes(bytes(blob))
got = mc.all_profile_names(root)
check("the recent-track names read back", got[: len(wanted)] == wanted, str(got))
check("an absent profile is not a crash", mc.all_profile_names(SANDBOX / "nothing") == [])

print("\npairing a name to a file, only when it is unambiguous")
base = ["Beaver County Race 01"]
check("one track and one new name pair up",
      mc.learn_name(["NAT05"], base, ["Munchberry Farms"] + base) == ("NAT05", "Munchberry Farms"))
check("two tracks changed: refuses",
      mc.learn_name(["NAT05", "SX11"], base, ["Munchberry Farms"] + base) is None)
check("two new names: refuses",
      mc.learn_name(["NAT05"], base, ["A", "B"] + base) is None)
check("nothing new and no reorder: refuses",
      mc.learn_name(["NAT05"], base, base) is None)
check("a reorder names the track that moved to the front",
      mc.learn_name(["NAT05"], ["A", "B"], ["B", "A"]) == ("NAT05", "B"))
check("a name that just repeats the filename is not worth learning",
      mc.learn_name(["TD_Making_Tracks"], [], ["TD Making Tracks"]) is None)

print("\nthe bike class, read from the rider profile")


def with_class(size) -> Path:
    """An install whose rider profile has a given engine size selected."""
    home = SANDBOX / f"prof{size}"
    d = home / "UI" / "PROFILE" / "xSHXDEx"
    d.mkdir(parents=True, exist_ok=True)
    blob = bytearray(b"\0" * 4760)
    if size is not None:
        struct.pack_into("<I", blob, mc.PROFILE_CLASS_AT, size)
    (d / "xSHXDEx.prf").write_bytes(bytes(blob))
    return home


check("a 125 reads back as 125cc", mc.selected_class(with_class(125)) == "125cc")
check("a 500 reads back as 500cc", mc.selected_class(with_class(500)) == "500cc")
check("every class the game offers is accepted",
      all(mc.selected_class(with_class(c)) == f"{c}cc" for c in mc.CLASSES))
check("a value that is not a class is refused", mc.selected_class(with_class(3)) == "",
      "a wrong class on a published time is worse than none")
check("an empty profile gives nothing", mc.selected_class(with_class(0)) == "")
check("no profile at all gives nothing", mc.selected_class(SANDBOX / "nothing") == "")

# Two riders on different bikes: nothing on disk says which of them rode.
two = SANDBOX / "twoprofiles"
for who, size in (("a", 125), ("b", 500)):
    d = two / "UI" / "PROFILE" / who
    d.mkdir(parents=True, exist_ok=True)
    blob = bytearray(b"\0" * 4760)
    struct.pack_into("<I", blob, mc.PROFILE_CLASS_AT, size)
    (d / f"{who}.prf").write_bytes(bytes(blob))
check("two profiles disagreeing gives nothing", mc.selected_class(two) == "")

short = SANDBOX / "shortprof" / "UI" / "PROFILE" / "x"
short.mkdir(parents=True, exist_ok=True)
(short / "x.prf").write_bytes(b"\0" * 16)
check("a truncated profile is not a crash",
      mc.selected_class(SANDBOX / "shortprof") == "")

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all motocross checks passed")
