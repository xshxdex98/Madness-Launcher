"""The load-order list some engines keep alongside their archives.

Monster Truck Madness does not encode load order in filenames the way the
Midtown games do. `MONSTER.EXE` reads `pod.ini`, whose first line is a count and
whose remaining lines are archive paths in load order:

    7
    system\\ui.pod
    system\\startup.pod
    ...

Enabling a mod therefore means adding a line here, not renaming a file — and
because the paths are relative to the game folder, an archive already sitting in
the game can simply be pointed at where it is, with nothing copied at all.

The count on the first line has to stay in step with the list; the engine warns
"Too many .POD files at once!" when it is unhappy, so it is clearly load-bearing.
"""

from __future__ import annotations

from pathlib import Path

from .textfile import read_text, write_text_atomic


class CountedListFile:
    """A file whose first line is a count and whose rest are entries."""

    def __init__(
        self,
        path: Path,
        entries: list[str],
        newline: str = "\r\n",
        trailing: str = "",
        encoding: str = "utf-8",
    ):
        self.path = Path(path)
        self.entries = entries
        self._newline = newline
        # Whatever blank lines the original ended with, kept verbatim.
        self._trailing = trailing
        # The encoding the file was read as, so it is written back the same way.
        self._encoding = encoding

    @classmethod
    def load(cls, path: Path) -> "CountedListFile":
        path = Path(path)
        # read_text picks an encoding that round-trips. MTM2's pod.ini names a
        # track with byte 0xAC, which is not valid UTF-8; decoding that with
        # errors="replace" and saving would rewrite the entry and lose the track.
        raw, encoding = read_text(path)
        newline = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.splitlines()

        # Preserve the run of blank lines at the end, which the shipped file has.
        trailing_count = 0
        while lines and not lines[-1].strip():
            lines.pop()
            trailing_count += 1
        trailing = newline * trailing_count

        # The first line is the count, not an entry — drop it if it is a number.
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        entries = [line.strip() for line in lines if line.strip()]
        return cls(path, entries, newline, trailing, encoding)

    # -- normalising -----------------------------------------------------

    @staticmethod
    def normalise(entry: str) -> str:
        """Compare paths the way the engine's own file writes them."""
        return entry.replace("/", "\\").strip().lower()

    def contains(self, entry: str) -> bool:
        target = self.normalise(entry)
        return any(self.normalise(e) == target for e in self.entries)

    def add(self, entry: str) -> bool:
        """Append an entry unless it is already listed. Returns True if added."""
        entry = entry.replace("/", "\\").strip()
        if not entry or self.contains(entry):
            return False
        self.entries.append(entry)
        return True

    def remove(self, entry: str) -> bool:
        target = self.normalise(entry)
        before = len(self.entries)
        self.entries = [e for e in self.entries if self.normalise(e) != target]
        return len(self.entries) != before

    # -- writing ---------------------------------------------------------

    def text(self) -> str:
        lines = [str(len(self.entries))] + self.entries
        return self._newline.join(lines) + self._newline + self._trailing

    def save(self) -> None:
        write_text_atomic(self.path, self.text(), self._encoding)
