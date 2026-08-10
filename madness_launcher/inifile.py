"""A surgical INI editor.

configparser is the obvious tool and the wrong one here: it discards comments
and rewrites formatting wholesale. mm2hook.ini is 160 lines of carefully
annotated defaults — every setting documented inline, with its default noted —
and handing the user back a stripped version would destroy the only
documentation they have.

So this edits lines in place. Changing a value rewrites exactly the value span
of one line; the key, the padding, the inline comment and every other line come
back byte-for-byte.
"""

from __future__ import annotations

import re
from pathlib import Path

from .textfile import read_text, write_text_atomic

# Splits `  Key = value   ; comment` into its parts, keeping the whitespace so
# the line can be reassembled without drift.
_ENTRY = re.compile(
    r"^(?P<pre>\s*)"
    r"(?P<key>[A-Za-z0-9_.\-]+)"
    r"(?P<pad1>\s*)=(?P<pad2>\s*)"
    r"(?P<value>[^;#]*?)"
    r"(?P<post>\s*(?:[;#].*)?)$"
)
_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")


class IniFile:
    def __init__(
        self,
        path: Path,
        lines: list[str],
        newline: str = "\n",
        trailing_newline: bool = True,
        encoding: str = "utf-8",
    ):
        self.path = Path(path)
        self._lines = lines
        self._newline = newline
        self._trailing_newline = trailing_newline
        self._encoding = encoding
        self._index: dict[tuple[str, str], int] = {}
        self._sections: dict[str, tuple[int, int]] = {}
        self._reindex()

    # -- loading ---------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "IniFile":
        path = Path(path)
        # Read bytes, not text: text mode applies universal-newline translation,
        # which turns every CRLF into LF before the line ending can be detected —
        # and would then silently rewrite the user's whole file on the next save.
        # read_text also picks an encoding that round-trips: these files can
        # contain bytes that are not valid UTF-8 at all, and replacing them
        # would corrupt the entry on save. See textfile.py.
        raw, encoding = read_text(path)
        newline = "\r\n" if "\r\n" in raw else "\n"
        return cls(
            path,
            raw.splitlines(),
            newline,
            trailing_newline=raw.endswith(("\n", "\r")),
            encoding=encoding,
        )

    def _reindex(self) -> None:
        self._index.clear()
        self._sections.clear()
        section = ""
        start = 0
        for i, line in enumerate(self._lines):
            match = _SECTION.match(line)
            if match:
                if section:
                    self._sections[section.lower()] = (start, i)
                section = match.group("name").strip()
                start = i + 1
                continue
            entry = _ENTRY.match(line)
            if entry and section:
                self._index[(section.lower(), entry.group("key").lower())] = i
        if section:
            self._sections[section.lower()] = (start, len(self._lines))

    # -- reading ---------------------------------------------------------

    def get(self, section: str, key: str) -> str | None:
        index = self._index.get((section.lower(), key.lower()))
        if index is None:
            return None
        match = _ENTRY.match(self._lines[index])
        return match.group("value").strip() if match else None

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        try:
            return int(float((self.get(section, key) or "").strip()))
        except (TypeError, ValueError):
            return default

    def get_float(self, section: str, key: str, default: float = 0.0) -> float:
        try:
            return float((self.get(section, key) or "").strip())
        except (TypeError, ValueError):
            return default

    def has(self, section: str, key: str) -> bool:
        return (section.lower(), key.lower()) in self._index

    def sections(self) -> list[str]:
        return list(self._sections)

    # -- writing ---------------------------------------------------------

    def set(self, section: str, key: str, value) -> None:
        text = self._format(value)
        index = self._index.get((section.lower(), key.lower()))
        if index is None:
            self._insert(section, key, text)
            return

        match = _ENTRY.match(self._lines[index])
        if match is None:  # pragma: no cover - indexed lines always match
            return

        post = match.group("post")
        old = match.group("value")
        # Keep any inline comment in the column it started in, so a shorter
        # value does not drag the documentation left.
        if post.strip() and len(text) < len(old):
            text = text + " " * (len(old) - len(text))

        self._lines[index] = (
            f"{match.group('pre')}{match.group('key')}{match.group('pad1')}="
            f"{match.group('pad2')}{text}{post}"
        )

    @staticmethod
    def _format(value) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            # Avoid 0.10000000000000001 creeping into a tidy file.
            return f"{value:g}"
        return str(value)

    def _insert(self, section: str, key: str, text: str) -> None:
        """Add a key the file did not have, creating the section if needed."""
        bounds = self._sections.get(section.lower())
        if bounds is None:
            if self._lines and self._lines[-1].strip():
                self._lines.append("")
            self._lines.append(f"[{section}]")
            self._lines.append(f"{key}={text}")
        else:
            end = bounds[1]
            while end > bounds[0] and not self._lines[end - 1].strip():
                end -= 1
            self._lines.insert(end, f"{key}={text}")
        self._reindex()

    def save(self) -> None:
        """Write atomically; a half-written config file would be worse than none."""
        write_text_atomic(self.path, self.text(), self._encoding)

    def text(self) -> str:
        body = self._newline.join(self._lines)
        return body + self._newline if self._trailing_newline else body
