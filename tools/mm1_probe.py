"""Work out which record slot belongs to which Midtown Madness race.

The .dat files say what time was set, in what car, by whom — but not which
race it was for. Slots group in tens and the order is whatever the game's
internal race list happens to be, which no amount of staring at the file will
reveal. So establish it by experiment, one race at a time:

    python tools/mm1_probe.py snapshot
    ... play ONE race in Midtown Madness, beat your time, quit the game ...
    python tools/mm1_probe.py diff "Museum Marathon"

The diff prints which slot changed and, given a name, the line to paste into
RACE_NAMES in madness_launcher/records/mm1.py. Repeat per race; each run
costs one race and pins one name down for good.

    python tools/mm1_probe.py dump      # everything currently in the tables

The install is read from the launcher's own config, so there is nothing to
configure here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from madness_launcher.records import mm1  # noqa: E402

STATE = Path(__file__).with_name("mm1_probe_snapshot.json")


def install_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    config = Path(base) / "MadnessLauncher" / "config.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit(f"Could not read {config}. Configure Midtown Madness first.")
    path = ((data.get("installs") or {}).get("mm1") or {}).get("path")
    if not path:
        sys.exit("Midtown Madness is not configured in the launcher.")
    return Path(path)


def as_json(records: dict) -> str:
    return json.dumps(
        {
            f"{k[0]}|{k[1]}|{k[2]}": [v.driver, v.car, v.seconds]
            for k, v in records.items()
        },
        indent=2,
    )


def from_json(raw: str) -> dict:
    out = {}
    for key, (driver, car, seconds) in json.loads(raw).items():
        city, difficulty, slot = key.split("|")
        out[(city, difficulty, int(slot))] = mm1.LapRecord(
            slot=int(slot), driver=driver, car=car, seconds=seconds,
            city=city, difficulty=difficulty,
        )
    return out


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "dump"
    install = install_path()
    files = mm1.record_files(install)
    if not files:
        sys.exit(f"No players/*/*.dat under {install}. Has the game been run?")

    if command == "snapshot":
        current = mm1.snapshot(install)
        STATE.write_text(as_json(current), encoding="utf-8")
        print(f"Snapshot taken: {len(current)} records across {len(files)} files.")
        print("Now play ONE race, beat your existing time, and quit the game.")
        print(f'Then: python {Path(__file__).name} diff "Name Of That Race"')
        return 0

    if command == "diff":
        if not STATE.is_file():
            sys.exit("No snapshot yet. Run: mm1_probe.py snapshot")
        before = from_json(STATE.read_text(encoding="utf-8"))
        after = mm1.snapshot(install)
        changed = mm1.improvements(before, after)
        if not changed:
            print("Nothing changed. The time has to actually beat the stored one")
            print("for the game to write it, so a slower run leaves the file alone.")
            return 1

        name = argv[1] if len(argv) > 1 else ""
        print(f"{len(changed)} slot(s) changed:\n")
        races = sorted({r.race for r in changed})
        for record in changed:
            was = before.get(record.key())
            previous = f"{was.formatted} -> " if was else "new: "
            print(
                f"  {record.city}/{record.difficulty} slot {record.slot:3} "
                f"(race {record.race}, sub-slot {record.slot % 10})  "
                f"{previous}{record.formatted}  {record.car_name}  {record.driver}"
            )
        print()
        if len(races) == 1 and name:
            print("Add this to RACE_NAMES in madness_launcher/records/mm1.py:")
            print(f'    {races[0]}: "{name}",')
        elif len(races) > 1:
            print(f"More than one race changed ({races}) — the mapping is only")
            print("unambiguous when a single race is played between snapshots.")
        elif not name:
            print(f"Race index is {races[0]}. Re-run with the race's name to get")
            print("the line to paste.")
        return 0

    if command == "dump":
        current = mm1.snapshot(install)
        print(f"{len(current)} records in {len(files)} file(s) under {install}\n")
        for key in sorted(current):
            r = current[key]
            print(
                f"  {r.city}/{r.difficulty} slot {r.slot:3} "
                f"(race {r.race}, sub {r.slot % 10})  "
                f"{r.formatted:>10}  {r.car_name:<20} {r.driver}"
            )
        return 0

    sys.exit(f"Unknown command {command!r}. Use snapshot, diff or dump.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
