"""Work out where Motocross Madness 2 keeps the bike class.

Standalone on purpose. Nothing here touches the launcher's data, and nothing
is ever written into the game folder — the whole install is fingerprinted on
the way past so that can be shown rather than asserted.

What is already established, by reading real files:

    * a track's records live beside its .env as <track>.hs1, 208 bytes:
      an 8-byte header whose second word is the number of entries, then ten
      slots of a 16-byte name and a float32 of seconds. 0x7F7FFFFF marks an
      empty slot.
    * the discipline is the TERAFORM subfolder — SX, NATIONAL, ENDURO, BAJA,
      QUARRIES, TAG.
    * the engine classes are 125, 250, 350, 500 and 600cc, named in LANG.DLL.

What is NOT established is where the class of a given time is recorded. A
slot has room for a name and a time and nothing else, so either it is not
recorded at all, or it lives in the rider profile and belongs to whatever was
selected at the time. The first word of the .hs1 header is a candidate: it
reads 2 on every National file here, 3 on every Supercross one and 5 on the
Enduro, which looks like the discipline but could be something else entirely.

Guessing this is how the Midtown Madness 2 race order went wrong twice, so:

    python tools/mcm2_probe.py snapshot
    ... ride ONE track on 125cc, finish, back to the menu ...
    python tools/mcm2_probe.py diff
    ... ride the SAME track on 500cc, finish, back to the menu ...
    python tools/mcm2_probe.py diff

Any field that follows the class will show up in the second diff and not the
first. If nothing does, the class is not recorded and the launcher has to
read the current selection as the time is set.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

HEADER = 8
SLOT = 20
NAME_BYTES = 16
SLOTS = 10
EMPTY = 0x7F7FFFFF

# Anything above this is the empty-slot sentinel rather than a lap somebody
# rode. Real times are seconds; the sentinel is 3.4e38.
MAX_TIME = 1e6

DISCIPLINES = {
    "SX": "Supercross",
    "NATIONAL": "Nationals",
    "ENDURO": "Enduro",
    "BAJA": "Baja",
    "QUARRIES": "Stunt Quarry",
    "TAG": "Tag",
}

STATE = Path(__file__).with_name("mcm2_probe_snapshot.json")


def install_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    config = Path(base) / "MadnessLauncher" / "config.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit(f"Could not read {config}.")
    path = ((data.get("installs") or {}).get("mcm2") or {}).get("path")
    if not path:
        sys.exit("Motocross Madness 2 is not configured in the launcher.")
    return Path(path)


def parse_hs1(blob: bytes) -> tuple[int, int, list[tuple[str, float]]]:
    """(first header word, stated count, [(rider, seconds)]) from one .hs1."""
    if len(blob) < HEADER + SLOTS * SLOT:
        return 0, 0, []
    kind, count = struct.unpack_from("<2I", blob, 0)
    rows = []
    for i in range(SLOTS):
        off = HEADER + i * SLOT
        name = blob[off : off + NAME_BYTES].split(b"\0")[0]
        seconds = struct.unpack_from("<f", blob, off + NAME_BYTES)[0]
        if seconds >= MAX_TIME:
            continue
        rows.append((name.decode("latin-1", "replace"), round(seconds, 4)))
    return kind, count, rows


def tables(install: Path) -> dict[str, str]:
    """Every .hs1 under TERAFORM, as hex, keyed by discipline/track."""
    out = {}
    for path in sorted((install / "TERAFORM").rglob("*.hs1")):
        out[f"{path.parent.name}/{path.stem}"] = path.read_bytes().hex()
    return out


def profiles(install: Path) -> dict[str, str]:
    """Rider profiles and control maps, as hex. Small enough to keep whole."""
    out = {}
    root = install / "UI" / "PROFILE"
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.stat().st_size <= 65536:
                out[path.relative_to(root).as_posix()] = path.read_bytes().hex()
    return out


def fingerprint(install: Path) -> dict[str, list]:
    """Size and mtime of everything, so a stray write cannot go unnoticed."""
    out = {}
    for path in sorted(install.rglob("*")):
        if path.is_file():
            st = path.stat()
            out[path.relative_to(install).as_posix()] = [st.st_size, int(st.st_mtime)]
    return out


def take(install: Path) -> dict:
    return {
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "tables": tables(install),
        "profiles": profiles(install),
        "fingerprint": fingerprint(install),
    }


def fmt(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:06.3f}" if minutes else f"{rest:.3f}"


def diff_bytes(old: str, new: str, label: str) -> list[str]:
    """Report which 4-byte words of a small file changed, and to what."""
    a, b = bytes.fromhex(old), bytes.fromhex(new)
    lines = []
    if len(a) != len(b):
        lines.append(f"  {label}: size {len(a)} -> {len(b)}")
    n = min(len(a), len(b))
    runs = []
    for i in range(n):
        if a[i] != b[i]:
            if runs and i <= runs[-1][-1] + 4:
                runs[-1].append(i)
            else:
                runs.append([i])
    for run in runs:
        lo = run[0] - (run[0] % 4)
        hi = min(n, run[-1] + 4 - (run[-1] % 4) + 1)
        for off in range(lo, hi, 4):
            if off + 4 > n:
                break
            was = struct.unpack_from("<I", a, off)[0]
            now = struct.unpack_from("<I", b, off)[0]
            if was == now:
                continue
            wf = struct.unpack_from("<f", a, off)[0]
            nf = struct.unpack_from("<f", b, off)[0]
            extra = ""
            if 0.01 < abs(nf) < 1e6 or 0.01 < abs(wf) < 1e6:
                extra = f"   as float {wf:.4g} -> {nf:.4g}"
            note = ""
            for cc in (125, 250, 350, 500, 600):
                if now == cc or was == cc:
                    note = "   <-- an engine class!"
            lines.append(
                f"  {label} +{off:<5} {was:>11} -> {now:<11}"
                f" (0x{was:08x} -> 0x{now:08x}){extra}{note}"
            )
    return lines


def report_tables(current: dict) -> None:
    print(f"{len(current['tables'])} track(s) with recorded times:\n")
    for key, hexed in current["tables"].items():
        cat, track = key.split("/", 1)
        kind, count, rows = parse_hs1(bytes.fromhex(hexed))
        label = DISCIPLINES.get(cat.upper(), cat)
        print(f"  {label:13} {track:24} header=({kind},{count})")
        for name, secs in rows:
            print(f"        {fmt(secs):>10}  {name}")


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "dump"
    install = install_path()
    if not install.is_dir():
        sys.exit(f"{install} is not there.")
    current = take(install)

    if command == "dump":
        report_tables(current)
        return 0

    if command == "snapshot":
        STATE.write_text(json.dumps(current, indent=1), encoding="utf-8")
        print(f"Snapshot taken at {current['when']}.")
        print(f"  {len(current['tables'])} .hs1 tables")
        print(f"  {len(current['profiles'])} profile file(s)")
        print(f"  {len(current['fingerprint'])} files fingerprinted")
        print("\nNow ride ONE track, finish the race, and come back to the")
        print("menu so the game writes its files. Then:")
        print("   python tools/mcm2_probe.py diff")
        return 0

    if command == "diff":
        if not STATE.is_file():
            sys.exit("No snapshot yet. Run: python tools/mcm2_probe.py snapshot")
        before = json.loads(STATE.read_text(encoding="utf-8"))
        print(f"Comparing against the snapshot from {before['when']}.\n")

        print("=== record tables ===")
        keys = sorted(set(before["tables"]) | set(current["tables"]))
        moved = False
        for key in keys:
            old, new = before["tables"].get(key), current["tables"].get(key)
            if old == new:
                continue
            moved = True
            cat, track = key.split("/", 1)
            print(f"\n  {DISCIPLINES.get(cat.upper(), cat)} / {track}")
            if old is None:
                print("    NEW table")
            else:
                k0, c0, r0 = parse_hs1(bytes.fromhex(old))
                print(f"    was header=({k0},{c0}) {[(n, fmt(s)) for n, s in r0]}")
            k1, c1, r1 = parse_hs1(bytes.fromhex(new))
            print(f"    now header=({k1},{c1}) {[(n, fmt(s)) for n, s in r1]}")
            if old is not None:
                for line in diff_bytes(old, new, "    hs1"):
                    print(line)
        if not moved:
            print("  nothing changed — the game only keeps a time that beats")
            print("  what is already in the table.")

        print("\n=== rider profile ===")
        touched = False
        for key in sorted(set(before["profiles"]) | set(current["profiles"])):
            old, new = before["profiles"].get(key), current["profiles"].get(key)
            if old == new:
                continue
            touched = True
            if old is None or new is None:
                print(f"  {key}: {'added' if old is None else 'removed'}")
                continue
            lines = diff_bytes(old, new, f"  {key}")
            print(f"  {key}: {len(lines)} word(s) changed")
            for line in lines[:60]:
                print(line)
            if len(lines) > 60:
                print(f"    ... and {len(lines) - 60} more")
        if not touched:
            print("  unchanged")

        print("\n=== anything else in the game folder ===")
        changed = [
            name
            for name, meta in current["fingerprint"].items()
            if before["fingerprint"].get(name) != meta
            and not name.lower().endswith((".hs1", ".prf", ".ctl"))
        ]
        gone = sorted(set(before["fingerprint"]) - set(current["fingerprint"]))
        if changed or gone:
            print(f"  {len(changed)} changed, {len(gone)} removed:")
            for name in (changed + gone)[:20]:
                print(f"    {name}")
        else:
            print("  nothing else touched")
        return 0

    sys.exit(f"Unknown command {command!r}. Use snapshot, diff or dump.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
