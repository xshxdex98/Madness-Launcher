"""Reading and writing the game config files without damaging them.

These files predate UTF-8 and contain whatever bytes the era's tools wrote.
Monster Truck Madness 2's pod.ini names a track
`S+reaMII_C\\xacrazyT\\xacaiN.pod` — byte 0xAC, which is not valid UTF-8 at all.

Decoding that with `errors="replace"` turns the byte into U+FFFD, and writing
the file back encodes U+FFFD as three completely different bytes. The entry then
names a file that does not exist, and the game silently loses the track. One
toggle of an unrelated mod would have done that to a 98-entry list.

So: try UTF-8, and fall back to latin-1, which maps every byte 0-255 to a
codepoint and back again unchanged. Remember which was used so the file is
written back the way it was read. Round-tripping the bytes matters far more here
than interpreting them, since the launcher only ever compares ASCII filenames.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def read_text(path: Path) -> tuple[str, str]:
    """Return (text, encoding) for a legacy config file."""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # Byte-preserving fallback: latin-1 never fails and always round-trips.
        return raw.decode("latin-1"), "latin-1"


def write_text_atomic(path: Path, text: str, encoding: str) -> None:
    """Write the file in one step, in the encoding it was read as."""
    path = Path(path)
    if encoding == "utf-8-sig":
        data = b"\xef\xbb\xbf" + text.encode("utf-8")
    else:
        data = text.encode(encoding, errors="strict")

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise
