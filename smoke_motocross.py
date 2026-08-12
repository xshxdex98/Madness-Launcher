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

print("\nthrough the records pipeline")
from madness_launcher.records import store as record_store  # noqa: E402
from madness_launcher.records import tracknames  # noqa: E402
from madness_launcher.records.session import (  # noqa: E402
    GAMES_WITH_RECORDS,
    MOTOCROSS_GAMES,
    existing_records,
    plausible,
)

check("mcm2 is a game with records", "mcm2" in GAMES_WITH_RECORDS)
check("and is read the motocross way", "mcm2" in MOTOCROSS_GAMES)

full = install(
    {
        "SX/SX01": [("xSHXDEx", 72.909)],
        "NATIONAL/Nut_Buster": [("xSHXDEx", 95.195), ("Rival", 99.0)],
    },
    sizes={"Nut_Buster": 8243494},
)
subs = existing_records(full, "mcm2", "xSHXDEx")
check("every table becomes a record", len(subs) == 3, str(len(subs)))
sx = next(s for s in subs if s.track == "SX01")
nb = next(s for s in subs if s.track == "Nut_Buster")
check("a shipped track is on the vanilla board", sx.board == mc.BOARD_VANILLA)
check("a community track is on the modded board", nb.board == mc.BOARD_MODDED)
check("the discipline rides along", (sx.city, sx.race_kind) == ("SX", "Supercross"),
      f"{sx.city}/{sx.race_kind}")
check("an imported time claims no class", sx.car == "",
      "the profile only knows the bike selected now, not months ago")
check("the track filename is carried", sx.track == "SX01")

print("\n  a record survives the trip through the feed")
back = record_store._from_dict(sx.as_dict())
check("it comes back at all", back is not None)
if back is not None:
    same = (back.game, back.board, back.city, back.race, back.race_name,
            back.race_kind, back.track, back.seconds, back.driver)
    want = (sx.game, sx.board, sx.city, sx.race, sx.race_name,
            sx.race_kind, sx.track, sx.seconds, sx.driver)
    check("unchanged in every field the board reads", same == want,
          f"{same} != {want}")

print("\n  who owns which row")
def sub_for(track, folder, driver, secs, cls="250cc"):
    rec = mc.MotoRecord(track=track, folder=folder, driver=driver,
                        seconds=secs, stock=mc.is_stock(track, folder))
    from madness_launcher.records.session import _from_moto, SOURCE_LAUNCHER
    return _from_moto(rec, driver, cls, SOURCE_LAUNCHER, "2026-01-01T00:00:00")

mine = sub_for("SX01", "SX", "xSHXDEx", 72.909)
theirs = sub_for("SX01", "SX", "Rival", 71.0)
faster = sub_for("SX01", "SX", "xSHXDEx", 70.5)
merged = record_store.merge([], [mine, theirs])
check("two riders on one track are two rows", len(merged) == 2, str(len(merged)))
merged = record_store.merge(merged, [faster])
check("beating your own time replaces it", len(merged) == 2, str(len(merged)))
check("and the faster one is what is kept",
      min(r.seconds for r in merged if r.driver == "xSHXDEx") == 70.5)
other_class = sub_for("SX01", "SX", "xSHXDEx", 74.0, "125cc")
merged = record_store.merge(merged, [other_class])
check("a different class stands on its own", len(merged) == 3, str(len(merged)))

print("\n  plausibility")
ok, why = plausible(mine, 600.0)
check("a real lap in a real session passes", ok, why)
ok, why = plausible(sub_for("SX01", "SX", "x", 2.0), 600.0)
check("an impossible lap is refused", not ok, why)
ok, why = plausible(mine, 5.0)
check("a lap longer than its session is refused", not ok, why)

print("\n  names learned here reach the board")
tracknames.load()
mc.set_learned({})
check("unlearned, a track goes by its filename",
      mc.pretty_track("SX01") == "SX01")
tracknames.remember("SX01", "Week 01 - Seattle")
check("learned, it goes by its name",
      mc.pretty_track("SX01") == "Week 01 - Seattle")
check("and a record picks it up",
      sub_for("SX01", "SX", "x", 72.9).race_name == "Week 01 - Seattle")
check("learning the same track twice keeps the first",
      not tracknames.remember("SX01", "Something Else")
      and mc.pretty_track("SX01") == "Week 01 - Seattle")
check("names carried by the feed are adopted",
      tracknames.adopt({"NAT05": "Beaver County Race 01"}) == 1
      and mc.pretty_track("NAT05") == "Beaver County Race 01")
check("adopting one already known changes nothing",
      tracknames.adopt({"NAT05": "Wrong"}) == 0
      and mc.pretty_track("NAT05") == "Beaver County Race 01")
check("they survive a restart", tracknames.load().get("sx01") == "Week 01 - Seattle")

print("\nthe records page")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from madness_launcher.ui import records_page as rp  # noqa: E402

check("mcm2 has a board", "mcm2" in rp.SUPPORTED)
check("its boards are named for tracks",
      [label for _, label, _ in rp.boards_for("mcm2")] == ["Vanilla tracks", "Modded tracks"])
check("the Midtown boards are untouched",
      [label for _, label, _ in rp.boards_for("mm1")] == ["Vanilla", "Modded"])
check("its columns name tracks, classes and events",
      rp.columns_for("mcm2") == ("#", "Track", "Time", "Class", "Rider", "Event", "Source"))
check("the Midtown columns are untouched", rp.columns_for("mm1") == rp.COLUMNS)
check("it gets a tab per discipline", len(rp.cities_for("mcm2")) == 6,
      str(rp.cities_for("mcm2")))
check("every discipline tab has a label",
      all(c in rp.CITY_LABELS for c in rp.cities_for("mcm2")))
check("mm2 still gets its two cities", rp.cities_for("mm2") == ("london", "sf"))

view = rp.GameRecords("mcm2")
view.show_records([mine, theirs, nb], {"xSHXDEx"}, 0, True)
check("six discipline boards were built", len(view.cities) == 6, str(len(view.cities)))
sx_board = view.cities["sx"].views[mc.BOARD_VANILLA]
check("the Supercross vanilla board holds both riders",
      sx_board.tree.topLevelItemCount() == 2,
      str(sx_board.tree.topLevelItemCount()))
nat_board = view.cities["national"].views[mc.BOARD_MODDED]
check("the modded National board holds the community track",
      nat_board.tree.topLevelItemCount() == 1)
row = sx_board.tree.topLevelItem(0)
check("the event shows in its own column",
      row.text(rp.COL_DIFF) == "Supercross", row.text(rp.COL_DIFF))
check("the class shows", row.text(rp.COL_CAR) == "250cc", row.text(rp.COL_CAR))
check("the track name is not doubled up with the event",
      "·" not in row.text(rp.COL_RACE), row.text(rp.COL_RACE))

print("\nthe round trip through Discord and back")
sys.path.insert(0, str(ROOT / "tools" / "newsbot"))
from madness_launcher.records import submit as record_submit  # noqa: E402
import build_news  # noqa: E402

posted = sub_for("SX01", "SX", "xSHXDEx", 63.954, "500cc")
posted.race_name = "Week 01 - Seattle"

for label, text in (
    ("on its own", record_submit.describe(posted)),
    ("in a batch", record_submit.describe_batch([posted])),
):
    parsed = build_news.parse_records({"content": text, "id": "1"})
    check(f"a record posted {label} is read back", len(parsed) == 1,
          f"{len(parsed)} from {text!r}")
    if not parsed:
        continue
    got = parsed[0]
    check(f"  {label}: the track index survives", got["race"] == posted.race,
          f"{got['race']} != {posted.race} — the relay used to cap this at 999")
    check(f"  {label}: the time survives", got["seconds"] == 63.954, str(got["seconds"]))
    check(f"  {label}: the class survives", got["car"] == "500cc", got["car"])
    check(f"  {label}: the event survives", got["race_kind"] == "Supercross",
          f"{got['race_kind']!r} — without kind= the Event column is blank")
    check(f"  {label}: the track filename survives", got.get("track") == "SX01",
          f"{got.get('track')!r} — the learned name has nothing to key against")
    check(f"  {label}: the discipline survives", got["city"] == "SX", got["city"])
    check(f"  {label}: the board survives", got["board"] == mc.BOARD_VANILLA)

check(
    "a Midtown race index is still capped",
    build_news.parse_records(
        {"content": 'x\n`game="mm1" board="vanilla" race="5000" time="60.0"`', "id": "1"}
    ) == [],
    "the 999 ceiling still protects the games that have a fixed race list",
)
check(
    "and a Motocross one above 28 bits is refused",
    build_news.parse_records(
        {"content": f'x\n`game="mcm2" board="vanilla" race="{2**29}" time="60.0"`',
         "id": "1"}
    ) == [],
)

headline = record_submit.describe(posted).splitlines()[0]
check("the headline reads as a sentence", "(Supercross)" in headline
      and "on a 500cc" in headline and ", )" not in headline, headline)
print(f"  ({headline})")

# A batch has to fit Discord's limit, which is what truncated a post into a
# blank one before.
many = [sub_for(f"track{i:03}", "SX", "xSHXDEx", 60.0 + i, "250cc") for i in range(40)]
# pack() groups records; each group is rendered into one message.
messages = [record_submit.describe_batch(group) for group in record_submit.pack(many)]
check("a big batch is split into more than one message", len(messages) > 1,
      str(len(messages)))
check("and every message fits inside Discord's limit",
      all(len(m) <= 2000 for m in messages), str(sorted(len(m) for m in messages)))
total = sum(len(build_news.parse_records({"content": m, "id": "1"})) for m in messages)
check("and every record in it survives the split", total == len(many),
      f"{total}/{len(many)} — a message cut mid-record reads back as fewer")

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all motocross checks passed")
