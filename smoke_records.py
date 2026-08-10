"""Checks for lap records: reading them, judging them, and showing them.

Offline, with a .dat built in memory rather than a real game folder. The
interesting cases are all about data that is wrong on purpose — a time nobody
could drive, a car that is not in the game, a record that appeared without the
launcher watching — because those are the ones the board's usefulness depends
on catching, and none of them turn up by playing the game normally.
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "newsbot"))

SANDBOX = Path(tempfile.mkdtemp(prefix="madness-records-"))
os.environ["MADNESS_LAUNCHER_HOME"] = str(SANDBOX)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import build_news  # noqa: E402
from madness_launcher.config import Config, Settings  # noqa: E402
from madness_launcher.records import mm1, store  # noqa: E402
from madness_launcher.records.session import (  # noqa: E402
    MIN_PLAUSIBLE_SECONDS,
    Submission,
    plausible,
)
from madness_launcher.records.session import existing_records  # noqa: E402
from madness_launcher.records.submit import describe, usable_webhook  # noqa: E402
from madness_launcher.ui import theme  # noqa: E402
from madness_launcher.ui.records_page import SORTS, RecordsPage  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(theme.stylesheet())


def build_dat(entries: dict[int, tuple[str, str, float]]) -> bytes:
    """A .dat in the game's own layout, for slots we choose."""
    blob = bytearray(struct.pack("<II", mm1.MAGIC, 12))
    for slot in range(360):
        record = bytearray(mm1.RECORD)
        if slot in entries:
            driver, car, seconds = entries[slot]
            record[0:4] = b"\x01\x02\x03\x04"
            record[4 : 4 + len(driver)] = driver.encode()
            record[44 : 44 + len(car)] = car.encode()
            record[124:128] = struct.pack("<f", seconds)
            record[128:132] = struct.pack("<I", 1)
        blob += record
    return bytes(blob) + b"\x00" * 8


def write_install(entries: dict[int, tuple[str, str, float]]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mm1-"))
    city = root / "players" / "chicago"
    city.mkdir(parents=True)
    (city / "pro.dat").write_bytes(build_dat(entries))
    return root


print("the game's own table is read back correctly")
install = write_install(
    {
        0: ("Pan", "vpmustang99", 41.228),
        1: ("Pan", "vpmustang99", 450.0),   # par time, odd sub-slot
        2: ("Pan", "vpcaddie", 43.286),
        140: ("Pan", "vppanozgt", 101.5),
    }
)
records = mm1.parse(install / "players" / "chicago" / "pro.dat")
check("three real records", len(records) == 3, str(len(records)))
check("the par time is not one of them",
      all(abs(r.seconds - 450.0) > 0.01 for r in records))
check("driver read", records[0].driver == "Pan", records[0].driver)
check("car read", records[0].car == "vpmustang99", records[0].car)
check("time read", abs(records[0].seconds - 41.228) < 1e-3)
check("slot 140 is race 14", records[-1].race == 14, str(records[-1].race))
check("formatted as a lap time", records[-1].formatted == "1:41.500",
      records[-1].formatted)
check("sub-minute times omit the minutes", records[0].formatted == "41.228",
      records[0].formatted)

print("\na file that is not one of these is refused, not misread")
broken = install / "players" / "chicago" / "junk.dat"
broken.write_bytes(b"not a save file at all")
check("wrong magic yields nothing", mm1.parse(broken) == [])
check("a missing file yields nothing", mm1.parse(install / "nope.dat") == [])
empty = install / "players" / "chicago" / "empty.dat"
empty.write_bytes(struct.pack("<II", mm1.MAGIC, 12))
check("a header with no records yields nothing", mm1.parse(empty) == [])

print("\nonly improvements count as new records")
before = mm1.snapshot(install)
check("snapshot found them", len(before) == 3, str(len(before)))
check("nothing improved against itself", mm1.improvements(before, before) == [])
faster = write_install({0: ("Pan", "vpmustang99", 40.0)})
after = mm1.snapshot(faster)
# Same slot, different install root — the key is city/difficulty/slot.
moved = {k: v for k, v in after.items()}
check("a faster time is an improvement", len(mm1.improvements(before, moved)) == 1)
# A race holds a leaderboard, not one best time, and the game only writes an
# entry that earned a place on it. So a lap slower than the leader is still a
# new entry — it took second or third — and reporting it is correct.
slower = mm1.snapshot(write_install({0: ("Pan", "vpmustang99", 99.0)}))
check("a slower lap the game chose to store is still new",
      len(mm1.improvements(before, slower)) == 1)
check("but a table that did not change yields nothing",
      mm1.improvements(before, before) == [])
check("and re-reading the same file twice yields nothing",
      mm1.improvements(mm1.snapshot(install), mm1.snapshot(install)) == [])

print("\nthe stock roster decides which board a run belongs on")
check("stock car, no mods -> vanilla",
      mm1.classify("vpmustang99", []) == mm1.BOARD_VANILLA)
check("stock car, unapproved archive -> modded",
      mm1.classify("vpmustang99", ["pack.ar"]) == mm1.BOARD_MODDED)
check("custom car -> neither", mm1.classify("vpdisco", []) is None)
check("custom car with archives -> still neither",
      mm1.classify("vpeb184", ["pack.ar"]) is None)
check("case does not matter", mm1.is_vanilla_car("VPMUSTANG99"))
check("the roster is the stock ten", len(mm1.VANILLA_CARS) == 10,
      str(len(mm1.VANILLA_CARS)))


print("\nonly the allowlisted fixes keep a run on the vanilla board")


def archive_install(files: dict[str, bytes], staged: dict[str, bytes] | None = None):
    """A game folder with chosen archives at root, and some parked below it."""
    root = Path(tempfile.mkdtemp(prefix="mm1-ar-"))
    for name in ("core.ar", "audio.ar", "ui.ar", "1560.ar"):
        (root / name).write_bytes(b"base archive")
    for name, blob in files.items():
        (root / name).write_bytes(blob)
    if staged:
        sub = root / "Custom Racepacks"
        sub.mkdir()
        for name, blob in staged.items():
            (sub / name).write_bytes(blob)
    return root


# Reproduce an allowlisted archive exactly by size and digest without needing
# the real file: the check is content-addressed, so any bytes that hash to an
# allowlisted digest are by definition that file.
REAL = {h: n for h, n in mm1.VANILLA_ARCHIVES.items()}

clean = archive_install({})
check("a stock folder has nothing added", mm1.active_archives(clean) == [])
check("and classifies as vanilla",
      mm1.classify("vpmustang99", mm1.unapproved_archives(clean))
      == mm1.BOARD_VANILLA)

check("the game's own archives are never counted as mods",
      all(p.name.lower() not in mm1.BASE_ARCHIVES for p in mm1.active_archives(clean)))

racepack = archive_install({"!!!Chicago_Rebellion_RP.ar": b"racepack" * 500})
check("an added archive is seen", len(mm1.active_archives(racepack)) == 1)
check("an unknown archive is unapproved",
      mm1.unapproved_archives(racepack) == ["!!!Chicago_Rebellion_RP.ar"])
check("and pushes the run to the modded board",
      mm1.classify("vpmustang99", mm1.unapproved_archives(racepack))
      == mm1.BOARD_MODDED)

staged = archive_install({}, staged={"!!!BigRacepack.ar": b"x" * 5000})
check("archives parked in a subfolder are not loaded",
      mm1.active_archives(staged) == [])
check("so a staging folder does not make a run modded",
      mm1.classify("vpmustang99", mm1.unapproved_archives(staged))
      == mm1.BOARD_VANILLA)

print("\nthe allowlist is by content, so a filename proves nothing")
spoof = archive_install({"!!!!wsfix16to9.ar": b"a handling mod in disguise" * 100})
check("a mod wearing an allowlisted name is still unapproved",
      mm1.unapproved_archives(spoof) == ["!!!!wsfix16to9.ar"])
check("and lands on the modded board",
      mm1.classify("vpmustang99", mm1.unapproved_archives(spoof))
      == mm1.BOARD_MODDED)
check("every allowlisted entry is a sha256 digest",
      all(len(h) == 64 and all(c in "0123456789abcdef" for c in h)
          for h in mm1.VANILLA_ARCHIVES))
check("four fixes are allowed", len(mm1.VANILLA_ARCHIVES) == 4,
      str(len(mm1.VANILLA_ARCHIVES)))
check("their sizes are known so most files never get hashed",
      len(mm1._ALLOWED_SIZES) == 4)

digest_of = archive_install({"x.ar": b"known bytes"})
check("digesting a real file works",
      len(mm1.archive_digest(digest_of / "x.ar")) == 64)
check("digesting a missing file yields nothing",
      mm1.archive_digest(digest_of / "nope.ar") == "")


def entry(**kwargs) -> Submission:
    base = dict(
        game="mm1", board="vanilla", race=14, race_name="Museum Marathon",
        race_kind="Circuit", difficulty="pro", car="vpmustang99",
        car_name="Ford Mustang GT", seconds=101.234, driver="Pan",
        username="Tester", set_at="2026-08-10T18:00:00+00:00",
    )
    base.update(kwargs)
    return Submission(**base)


print("\na race holds a sorted leaderboard, so entries shift when one is added")
# Each race keeps its times in ascending order. Adding one pushes every
# slower entry down a slot, and a slot-by-slot diff reads each shift as a new
# record set by whoever moved into that slot — one real lap, several invented.
was = mm1.snapshot(write_install({
    0: ("Pan", "vpmustang99", 41.228),
    2: ("Pan", "vpcaddie", 43.286),
}))
now = mm1.snapshot(write_install({
    0: ("Pan", "vpmustang99", 41.228),
    2: ("Tester", "vppanozgt", 42.000),   # inserted in the middle
    4: ("Pan", "vpcaddie", 43.286),       # the same old lap, one slot down
}))
shifted = mm1.improvements(was, now)
check("only the genuinely new lap is reported", len(shifted) == 1,
      str([(r.car_name, r.formatted) for r in shifted]))
check("and it is the one that was driven",
      shifted and shifted[0].car == "vppanozgt", str(shifted))
check("the displaced entry is not reported as new",
      all(r.car != "vpcaddie" for r in shifted))
check("an unchanged table still yields nothing",
      mm1.improvements(was, was) == [])
check("a lap identical but for its driver counts as new",
      len(mm1.improvements(was, mm1.snapshot(write_install({
          0: ("Pan", "vpmustang99", 41.228),
          2: ("Someone", "vpcaddie", 43.286),
      })))) == 1)

print("\na time survives a round trip without appearing to get faster")
# The .dat holds a float32. Writing three decimals and reading them back used
# to yield a value LARGER than the original, so on every startup the same lap
# looked freshly beaten by a fraction of a millisecond — a duplicate record
# published on every launch, forever.
drifty = write_install({0: ("Pan", "vpmustang99", 120.0417709350586)})
parsed_once = mm1.snapshot(drifty)
round_tripped = store.from_feed(
    [r.as_dict() for r in store.merge([], existing_records(drifty, "mm1", "T"))]
)
check("the parsed time is quantised",
      abs(list(parsed_once.values())[0].seconds - 120.042) < 1e-9,
      repr(list(parsed_once.values())[0].seconds))
check("and matches after a trip through JSON",
      round_tripped and abs(round_tripped[0].seconds - 120.042) < 1e-9,
      repr(round_tripped[0].seconds if round_tripped else None))
check("so re-reading the same save finds nothing new",
      mm1.improvements(mm1.snapshot(drifty), mm1.snapshot(drifty)) == [])
stored_again = store.merge(round_tripped, existing_records(drifty, "mm1", "T"))
check("and re-importing it does not add a duplicate",
      len(stored_again) == len(round_tripped), str(len(stored_again)))

print("\na player's existing times are taken in, not ignored")

history = write_install({
    0: ("Pan", "vpmustang99", 41.228),
    1: ("Pan", "vpmustang99", 450.0),      # par time, must not be imported
    2: ("Pan", "vpcaddie", 43.286),
    30: ("Pan", "vppanozgt", 74.811),
    40: ("Pan", "vpdisco", 60.0),          # custom car, belongs on no board
})
mm1.load_city(None)
imported = existing_records(history, "mm1", "Tester")
check("times already on disk are imported", len(imported) == 3,
      str([(r.race_name, r.formatted) for r in imported]))
check("they are marked as imported, not as witnessed",
      all(r.source == "imported" for r in imported))
check("par times are still excluded",
      all(abs(r.seconds - 450.0) > 0.01 for r in imported))
check("a custom car is still excluded",
      all(r.car != "vpdisco" for r in imported))
check("they carry the launcher username",
      all(r.username == "Tester" for r in imported))
check("and land on the vanilla board in a clean folder",
      all(r.board == mm1.BOARD_VANILLA for r in imported))

merged_once = store.merge([], imported)
check("importing twice changes nothing",
      len(store.merge(merged_once, imported)) == len(merged_once))
faster_now = existing_records(
    write_install({0: ("Pan", "vpmustang99", 39.000)}), "mm1", "Tester")
after_pb = store.merge(merged_once, faster_now)
best = [r for r in after_pb if r.race == 0 and r.difficulty == "pro"][0]
check("a later personal best replaces the imported one",
      abs(best.seconds - 39.000) < 1e-3, best.formatted)

print("\nmany records go out in few messages")
from madness_launcher.records.submit import BATCH, describe_batch  # noqa: E402

many = [entry(race=i, race_name=f"Race {i}", seconds=40.0 + i) for i in range(3)]
one_message = describe_batch(many)
check("a batch carries every record", one_message.count("game=") == 3,
      str(one_message.count("game=")))
reparsed = build_news.parse_records({"id": "1", "content": one_message})
check("and the relay reads them all back", len(reparsed) == 3, str(len(reparsed)))
check("times survive the batch",
      sorted(round(r["seconds"], 3) for r in reparsed) == [40.0, 41.0, 42.0],
      str([r["seconds"] for r in reparsed]))
check("a single record is still sent the readable way",
      describe_batch([many[0]]) == describe(many[0]))
check("the batch size keeps a long history to a few posts",
      BATCH >= 5, str(BATCH))
check("provenance survives a batch",
      build_news.parse_records({"id": "1", "content": describe_batch(
          [entry(race=0, source="imported"), entry(race=1)])})[0]["source"]
      == "imported")

print("\nevery watched session reports back, even an empty one")
from madness_launcher.records.session import RecordWatcher  # noqa: E402


class _Exited:
    """Stands in for a game process that has already finished."""

    def poll(self):
        return 0


quiet = write_install({0: ("Pan", "vpmustang99", 41.228)})
watcher = RecordWatcher("mm1", quiet, _Exited(), username="Tester")
seen: list = []
watcher.found.connect(lambda e: seen.append(("found", len(e))))
watcher.finished.connect(lambda n: seen.append(("finished", n)))
watcher._collect()
check("a session that beat nothing still reports back",
      ("finished", 0) in seen, str(seen))
check("and reports that it found nothing",
      not any(s[0] == "found" for s in seen), str(seen))

improved = write_install({0: ("Pan", "vpmustang99", 35.1)})
watcher2 = RecordWatcher("mm1", quiet, _Exited(), username="Tester")
watcher2._before = mm1.snapshot(quiet)
watcher2.install = improved
# The watcher was built a moment ago, so without this the session looks zero
# seconds long and a 35-second lap is correctly judged not to fit in it.
watcher2._started -= 600
seen2: list = []
watcher2.found.connect(lambda e: seen2.append(("found", len(e))))
watcher2.finished.connect(lambda n: seen2.append(("finished", n)))
watcher2._collect()
check("a session that beat something reports the count",
      ("finished", 1) in seen2 and ("found", 1) in seen2, str(seen2))

print("\na record has to fit in the session that produced it")
check("a normal lap in a long session", plausible(entry(), 600)[0])
check("a lap longer than the session is refused",
      not plausible(entry(seconds=400.0), 60)[0])
check("but menu time is allowed for",
      plausible(entry(seconds=101.234), 90)[0])
check("a superhuman time is refused",
      not plausible(entry(seconds=MIN_PLAUSIBLE_SECONDS - 1), 600)[0])
check("an hour-plus lap is refused", not plausible(entry(seconds=4000.0), 9000)[0])
check("a custom car never passes", not plausible(entry(board=""), 600)[0])
check("an unnamed race is refused", not plausible(entry(race_name=""), 600)[0])
check("the reason is given", plausible(entry(seconds=2.0), 600)[1] != "")

print("\nthe board is only ever posted to Discord")
for url, ok in (
    ("https://discord.com/api/webhooks/1/abc", True),
    ("https://ptb.discord.com/api/webhooks/1/abc", True),
    ("https://evil.test/api/webhooks/1/abc", False),
    ("http://discord.com/api/webhooks/1/abc", False),
    ("https://discord.com/channels/1/2/3", False),
    ("https://discord.com.evil.test/api/webhooks/1/a", False),
    ("javascript:alert(1)", False),
    ("", False),
):
    check(f"{'accepts' if ok else 'refuses'} {url[:44] or '(empty)'}",
          bool(usable_webhook(url)) == ok)

print("\nthe message the launcher posts is the one the relay reads back")
message = describe(entry())
check("it is human-readable first", "Museum Marathon" in message)
check("it carries the machine-readable line", 'race="14"' in message, message)
parsed = build_news.parse_record({"id": "7", "content": message})
check("the relay parses it", parsed is not None)
if parsed:
    check("game survives", parsed["game"] == "mm1")
    check("board survives", parsed["board"] == "vanilla")
    check("race survives", parsed["race"] == 14)
    check("time survives", abs(parsed["seconds"] - 101.234) < 1e-3)
    check("name survives", parsed["race_name"] == "Museum Marathon")
    check("the message id is kept for moderation", parsed["message_id"] == "7")

print("\nthe relay re-checks what it reads, because anyone can post there")
for content, why in (
    ("just chatting", "not a record"),
    ('game="mm1" board="vanilla" race="1" time="0.2"', "impossibly fast"),
    ('game="mm1" board="vanilla" race="1" time="99999"', "impossibly slow"),
    ('game="mm1" board="godmode" race="1" time="60"', "invented board"),
    ('game="mm1" board="vanilla" race="-3" time="60"', "negative race"),
    ('game="mm1" board="vanilla" race="1" time="abc"', "unparseable time"),
    ('board="vanilla" race="1" time="60"', "no game"),
):
    check(f"refuses {why}", build_news.parse_record({"id": "1", "content": content}) is None)

print("\nonly the fastest claim per slot reaches the board")
msgs = [
    {"id": "1", "content": 'game="mm1" board="vanilla" race="5" diff="pro" time="90.0" by="A"'},
    {"id": "2", "content": 'game="mm1" board="vanilla" race="5" diff="pro" time="75.5" by="B"'},
    {"id": "3", "content": 'game="mm1" board="vanilla" race="5" diff="pro" time="88.0" by="C"'},
    {"id": "4", "content": 'game="mm1" board="modded"  race="5" diff="pro" time="60.0" by="D"'},
]
build_news.discord_messages = lambda c, t, l: msgs
collected, _ = build_news.collect_records(
    {"records": [{"channel_id": "1", "guild_id": "2"}]}, "token"
)
check("one row per board", len(collected) == 2, str(len(collected)))
vanilla = [r for r in collected if r["board"] == "vanilla"][0]
check("the fastest vanilla claim wins", abs(vanilla["seconds"] - 75.5) < 1e-3,
      str(vanilla["seconds"]))
check("and keeps its author", vanilla["username"] == "B", vanilla["username"])
check("the modded board is separate",
      any(r["board"] == "modded" for r in collected))

print("\nthe local store keeps only the best per slot")
saved = store.merge([], [entry(seconds=101.0), entry(seconds=99.0), entry(seconds=105.0)])
check("three attempts collapse to one", len(saved) == 1, str(len(saved)))
check("and it is the fastest", abs(saved[0].seconds - 99.0) < 1e-3)
check("a different board is its own row",
      len(store.merge(saved, [entry(board="modded", seconds=200.0)])) == 2)
check("a different difficulty is its own row",
      len(store.merge(saved, [entry(difficulty="amateur", seconds=200.0)])) == 2)

print("\nthe store survives a round trip and a corrupt file")
store.save(saved)
check("read back", len(store.load()) == 1)
store.store_file().write_text("{ not json", encoding="utf-8")
check("corrupt file yields nothing rather than raising", store.load() == [])
store.save(saved)

print("\npublished records are held to the same standard as local ones")
check("junk entries are dropped",
      len(store.from_feed([{"game": "mm1", "race": 1, "seconds": 60}, "junk", None])) == 1)
check("a negative race is dropped",
      store.from_feed([{"game": "mm1", "race": -1, "seconds": 60}]) == [])
check("a zero time is dropped",
      store.from_feed([{"game": "mm1", "race": 1, "seconds": 0}]) == [])
check("a car id becomes a readable name",
      store.from_feed([{"game": "mm1", "race": 1, "seconds": 60, "car": "vpbug"}])[0]
      .car_name != "vpbug")

print("\nsubmission is off unless it is switched on")
check("the default is off", Settings.from_dict({}).records_submit is False)
check("it round-trips", Settings.from_dict({"records_submit": True}).records_submit)

print("\nthe page groups by game and by board")
config = Config()
config.settings.username = "Tester"
rows = [
    entry(board="vanilla", race=0, race_name="Dearborn Dash", seconds=41.2),
    entry(board="vanilla", race=14, seconds=101.2, username="Someone"),
    entry(board="modded", race=0, race_name="Dearborn Dash", seconds=39.9),
]
page = RecordsPage(config, lambda: rows)
check("a tab per game", page.games.count() == 6, str(page.games.count()))
check("Midtown Madness has boards", "mm1" in page.views)
view = page.views["mm1"]
check("two boards", view.tabs.count() == 2, str(view.tabs.count()))
check("vanilla holds two rows",
      view.views["vanilla"].tree.topLevelItemCount() == 2,
      str(view.views["vanilla"].tree.topLevelItemCount()))
check("modded holds one",
      view.views["modded"].tree.topLevelItemCount() == 1)
check("counts appear on the board tabs", "2" in view.tabs.tabText(0),
      view.tabs.tabText(0))
first = view.views["vanilla"].tree.topLevelItem(0)
check("the race is named", "Dearborn Dash" in first.text(0), first.text(0))
check("the kind is shown", "Circuit" in first.text(0) or "Blitz" in first.text(0),
      first.text(0))
check("the time is shown", first.text(1) == "41.200", first.text(1))
check("your own row is marked", first.toolTip(0) != "", first.toolTip(0))
other = view.views["vanilla"].tree.topLevelItem(1)
check("somebody else's row is not", other.toolTip(0) == "", other.toolTip(0))

print("\nthe race table is always loaded, so named records can place")
# The bug this guards: nothing in the launcher loaded the table, so every
# record that names its race instead of numbering it — all of them from
# speedrun.com — failed to place and the board went quietly empty.
mm1.RACE_NAMES.clear()
mm1.RACE_KINDS.clear()
check("with no table loaded, a named record cannot place",
      store.from_feed([{"game": "mm1", "race_name": "Museum Marathon",
                        "seconds": 99.0}]) == [])
fallback = mm1.load_city(None)
check("a launcher with no install still gets a table",
      len(mm1.RACE_NAMES) == 32, str(len(mm1.RACE_NAMES)))
check("and says where it came from", fallback.source == "built-in",
      fallback.source)
check("named records now place",
      len(store.from_feed([{"game": "mm1", "race_name": "Museum Marathon",
                            "seconds": 99.0}])) == 1)
check("the built-in table matches the game's own ordering",
      mm1.race_label(0) == "Dearborn Dash"
      and mm1.race_label(14) == "Museum Marathon"
      and mm1.race_label(31) == "Frosty Finale",
      f"{mm1.race_label(0)} / {mm1.race_label(14)} / {mm1.race_label(31)}")
check("kinds come with it",
      mm1.race_kind(0) == "Blitz" and mm1.race_kind(14) == "Circuit"
      and mm1.race_kind(31) == "Checkpoint")

print("\nexternal records are placed by name, never by position")
check("a race name resolves", mm1.race_index_by_name("Museum Marathon") >= 0)
check("the site's spelling of Soldier Sneaker still matches",
      mm1.race_index_by_name("Solider Sneaker")
      == mm1.race_index_by_name("Soldier Sneaker"),
      "both spellings must land on one race")
check("an unknown race lands nowhere",
      mm1.race_index_by_name("Not A Real Race") == -1)
check("a record with no index is placed by its name",
      store.from_feed([{"game": "mm1", "board": "vanilla", "difficulty": "pro",
                        "race_name": "Museum Marathon", "seconds": 99.0,
                        "source": "speedrun.com"}])[0].race
      == mm1.race_index_by_name("Museum Marathon"))
check("a record with neither index nor known name is dropped",
      store.from_feed([{"game": "mm1", "race_name": "Nope", "seconds": 99.0}]) == [])
check("provenance survives",
      store.from_feed([{"game": "mm1", "race": 1, "seconds": 99.0,
                        "source": "speedrun.com"}])[0].source == "speedrun.com")
check("the race kind is derived once the race is known",
      store.from_feed([{"game": "mm1", "race_name": "Museum Marathon",
                        "seconds": 99.0}])[0].race_kind == "Circuit")
check("a hostile proof link is dropped",
      store.from_feed([{"game": "mm1", "race": 1, "seconds": 99.0,
                        "url": "javascript:alert(1)"}])[0].url == "")
check("a real proof link is kept",
      store.from_feed([{"game": "mm1", "race": 1, "seconds": 99.0,
                        "url": "https://www.speedrun.com/midtown1/runs/abc"}])[0].url
      != "")

print("\nthe table shows where a time came from")
sourced = RecordsPage(config, lambda: [
    # speedrun.com does not report a car, so this is what one really looks
    # like coming off the feed.
    entry(board="vanilla", race=0, race_name="Dearborn Dash", seconds=19.52,
          username="fatiyesman", source="speedrun.com", car="", car_name="",
          url="https://www.speedrun.com/midtown1/runs/zp5n7ogy"),
])
srow = sourced.views["mm1"].views["vanilla"].tree.topLevelItem(0)
check("the source column names it", srow.text(5) == "speedrun.com", srow.text(5))
check("the proof link is attached", bool(srow.data(0, Qt.UserRole)))
check("a run with no car is dashed, not blank", srow.text(2) == "—", srow.text(2))
plain = RecordsPage(config, lambda: [entry(board="vanilla", race=0)])
prow = plain.views["mm1"].views["vanilla"].tree.topLevelItem(0)
check("a launcher record leaves the source blank", prow.text(5) == "", prow.text(5))

print("\ntimes sort by value, not by how they are written")
# The case that makes this necessary: as text, "1:41.234" sorts before
# "41.228" because it starts with a 1.
spread = [
    entry(race=0, race_name="Dearborn Dash", seconds=41.228),
    entry(race=14, race_name="Museum Marathon", seconds=101.234),
    entry(race=5, race_name="Wild Blue Blitz", seconds=19.520),
    entry(race=9, race_name="Tall Tower Blitz", seconds=291.120),
]
sorted_page = RecordsPage(config, lambda: spread)
board = sorted_page.views["mm1"].views["vanilla"]


def shown_seconds() -> list:
    return [board.tree.topLevelItem(i)._keys[1]
            for i in range(board.tree.topLevelItemCount())]


def shown_races() -> list:
    return [board.tree.topLevelItem(i)._keys[0]
            for i in range(board.tree.topLevelItemCount())]


check("there is a sort control", sorted_page.sort_box.count() == len(SORTS),
      str(sorted_page.sort_box.count()))
check("it defaults to race order", sorted_page.sort_box.currentIndex() == 0)
check("race order really is race order", shown_races() == sorted(shown_races()))

sorted_page.sort_box.setCurrentIndex(1)
check("fastest first is ascending by value",
      shown_seconds() == sorted(shown_seconds()), str(shown_seconds()))
check("the fastest lap is on top", abs(shown_seconds()[0] - 19.520) < 1e-3,
      str(shown_seconds()[0]))
check("a sub-minute time outranks a longer one written with a colon",
      shown_seconds().index(41.228) < shown_seconds().index(101.234),
      "41.228 must beat 1:41.234")

sorted_page.sort_box.setCurrentIndex(2)
check("slowest first is descending by value",
      shown_seconds() == sorted(shown_seconds(), reverse=True))
check("the slowest lap is on top", abs(shown_seconds()[0] - 291.120) < 1e-3)

sorted_page.sort_box.setCurrentIndex(0)
check("switching back restores race order",
      shown_races() == sorted(shown_races()))

print("\nclicking a column header sorts on the same real values")
board.tree.sortItems(1, Qt.AscendingOrder)
check("the Time header sorts numerically",
      shown_seconds() == sorted(shown_seconds()))
board.tree.sortItems(3, Qt.AscendingOrder)
drivers = [board.tree.topLevelItem(i).text(3)
           for i in range(board.tree.topLevelItemCount())]
check("the Driver header sorts alphabetically",
      drivers == sorted(drivers, key=str.lower), str(drivers))

print("\nan empty board explains itself rather than sitting blank")
blank = RecordsPage(config, lambda: [])
blank_view = blank.views["mm1"].views["vanilla"]
check("the table is hidden", not blank_view.tree.isVisible())
check("a notice is shown instead", blank_view.empty.text() != "")
check("games without support say so",
      blank.games.tabText(1) == "Midtown Madness 2")

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all record checks passed")
