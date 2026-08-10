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

from PySide6.QtWidgets import QApplication  # noqa: E402

import build_news  # noqa: E402
from madness_launcher.config import Config, Settings  # noqa: E402
from madness_launcher.records import mm1, store  # noqa: E402
from madness_launcher.records.session import (  # noqa: E402
    MIN_PLAUSIBLE_SECONDS,
    Submission,
    plausible,
)
from madness_launcher.records.submit import describe, usable_webhook  # noqa: E402
from madness_launcher.ui import theme  # noqa: E402
from madness_launcher.ui.records_page import RecordsPage  # noqa: E402

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
slower = mm1.snapshot(write_install({0: ("Pan", "vpmustang99", 99.0)}))
check("a slower time is not", mm1.improvements(before, slower) == [])

print("\nthe stock roster decides which board a run belongs on")
check("stock car, no mods -> vanilla",
      mm1.classify("vpmustang99", []) == mm1.BOARD_VANILLA)
check("stock car, racepack -> modded",
      mm1.classify("vpmustang99", ["pack"]) == mm1.BOARD_MODDED)
check("custom car -> neither", mm1.classify("vpdisco", []) is None)
check("custom car with mods -> still neither",
      mm1.classify("vpeb184", ["pack"]) is None)
check("case does not matter", mm1.is_vanilla_car("VPMUSTANG99"))
check("the roster is the stock ten", len(mm1.VANILLA_CARS) == 10,
      str(len(mm1.VANILLA_CARS)))


def entry(**kwargs) -> Submission:
    base = dict(
        game="mm1", board="vanilla", race=14, race_name="Museum Marathon",
        race_kind="Circuit", difficulty="pro", car="vpmustang99",
        car_name="Ford Mustang GT", seconds=101.234, driver="Pan",
        username="Tester", set_at="2026-08-10T18:00:00+00:00",
    )
    base.update(kwargs)
    return Submission(**base)


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
