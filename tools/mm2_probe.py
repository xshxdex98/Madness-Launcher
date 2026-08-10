"""Work out which record slot belongs to which Midtown Madness 2 race.

Standalone on purpose. The launcher does not support MM2 records yet, and
this exists to settle the one fact that support is waiting on: the order the
game numbers its races in. Nothing here touches the launcher's code or its
data, and nothing is ever written into the game folder.

MM2 stores records the same way MM1 does, with three differences established
by inspecting real save files:

    * a 16-byte header rather than 8
    * a magic of 1 rather than 1234
    * two cities, london and sf, each with 320 slots (32 races of 10)

Within a race the entries alternate, exactly as in MM1: an even sub-slot is a
time somebody drove and the odd one after it is the game's par time. Every
odd entry across all four of the save files inspected is a round multiple of
25 seconds and no even one is.

What is NOT yet known is which race each group of ten slots refers to.
speedrun.com lists 32 races per city — Blitz 10, Circuit 10, Checkpoint 12 —
which matches the slot count exactly, but not the order they are numbered in.
MM1 numbers them Blitz, then Circuit, then Checkpoint; MM2 probably does the
same, and probably is not good enough to file somebody's world record under.

    python tools/mm2_probe.py snapshot
    ... play ONE race, note which, beat your time or place top three ...
    python tools/mm2_probe.py diff "SF Blitz: Golden Race"

The diff names the slot that moved. One race in each of two categories is
enough to settle the order for both cities.
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

HEADER = 16
RECORD = 132
MAGIC = 1
SLOTS_PER_RACE = 10

STATE = Path(__file__).with_name("mm2_probe_snapshot.json")


def install_path() -> Path:
    """The MM2 folder, from the launcher's config."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    config = Path(base) / "MadnessLauncher" / "config.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit(f"Could not read {config}.")
    path = ((data.get("installs") or {}).get("mm2") or {}).get("path")
    if not path:
        sys.exit("Midtown Madness 2 is not configured in the launcher.")
    return Path(path)


def parse(path: Path) -> dict[int, tuple[float, str, str]]:
    """Every real entry in one .dat, keyed by slot.

    Par times are skipped, as are slots with a set flag but no car — the same
    two rules that hold for MM1.
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return {}
    if len(blob) < HEADER + RECORD:
        return {}
    magic, _ = struct.unpack_from("<II", blob, 0)
    if magic != MAGIC:
        print(f"  warning: {path.name} has magic {magic}, expected {MAGIC}")
        return {}

    out: dict[int, tuple[float, str, str]] = {}
    for slot in range((len(blob) - HEADER) // RECORD):
        chunk = blob[HEADER + slot * RECORD:HEADER + (slot + 1) * RECORD]
        if not struct.unpack("<I", chunk[128:132])[0]:
            continue
        if slot % 2:                        # par time, not a lap anyone drove
            continue
        car = chunk[44:124].split(b"\x00")[0].decode("latin-1", "replace")
        if not car:
            continue
        seconds = round(struct.unpack("<f", chunk[124:128])[0], 3)
        name = chunk[4:44].split(b"\x00")[0].decode("latin-1", "replace")
        out[slot] = (seconds, car, name)
    return out


def snapshot(install: Path) -> dict[str, dict[int, tuple]]:
    found = {}
    for path in sorted(install.glob("players/*/*.dat")):
        key = f"{path.parent.name}/{path.stem}"
        found[key] = parse(path)
    return found


def fmt(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}" if minutes else f"{rest:.3f}"


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "dump"
    install = install_path()
    current = snapshot(install)
    if not current:
        sys.exit(f"No players/*/*.dat under {install}.")

    if command == "snapshot":
        STATE.write_text(
            json.dumps({k: {str(s): v for s, v in rows.items()}
                        for k, rows in current.items()}, indent=2),
            encoding="utf-8",
        )
        total = sum(len(r) for r in current.values())
        print(f"Snapshot taken: {total} entries across {len(current)} files.")
        for key, rows in current.items():
            print(f"   {key}: {len(rows)}")
        print("\nNow play ONE race and note exactly which it was, then:")
        print('   python tools/mm2_probe.py diff "SF Blitz: Golden Race"')
        return 0

    if command == "diff":
        if not STATE.is_file():
            sys.exit("No snapshot yet. Run: python tools/mm2_probe.py snapshot")
        raw = json.loads(STATE.read_text(encoding="utf-8"))
        before = {k: {int(s): tuple(v) for s, v in rows.items()}
                  for k, rows in raw.items()}

        moved = []
        for key, rows in current.items():
            old = before.get(key, {})
            for slot, (secs, car, name) in sorted(rows.items()):
                was = old.get(slot)
                if was is None or abs(was[0] - secs) > 1e-3:
                    moved.append((key, slot, was, (secs, car, name)))

        if not moved:
            print("Nothing changed.")
            print("The game only stores a time that beats the one already in")
            print("that slot, and only when the race was placed well enough.")
            return 1

        label = argv[1] if len(argv) > 1 else ""
        print(f"{len(moved)} slot(s) changed:\n")
        races = set()
        for key, slot, was, now in moved:
            secs, car, _ = now
            previous = f"{fmt(was[0])} -> " if was else "new: "
            races.add((key.split("/")[0], slot // SLOTS_PER_RACE))
            print(f"  {key} slot {slot:3}  race {slot // SLOTS_PER_RACE:2} "
                  f"sub {slot % SLOTS_PER_RACE}   {previous}{fmt(secs)}  {car}")

        print()
        if len(races) == 1:
            city, race = races.pop()
            if label:
                print(f"So in {city}, race index {race} is {label!r}.")
                print(f'    {city} race {race} -> "{label}"')
            else:
                print(f"City {city}, race index {race}. Re-run with the race's")
                print("name in quotes to record the mapping.")
        else:
            print(f"More than one race moved ({sorted(races)}) — the mapping is")
            print("only unambiguous when a single race is played per snapshot.")
        return 0

    if command == "dump":
        for key, rows in current.items():
            print(f"=== {key}: {len(rows)} entries ===")
            for slot, (secs, car, name) in sorted(rows.items()):
                print(f"   slot {slot:3} (race {slot // SLOTS_PER_RACE:2}, "
                      f"sub {slot % SLOTS_PER_RACE}) {fmt(secs):>10}  {car}")
        return 0

    sys.exit(f"Unknown command {command!r}. Use snapshot, diff or dump.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
