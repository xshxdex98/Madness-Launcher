"""The user's chosen name.

Constrained by IRC rather than by taste: the chat room is an IRC channel, and a
name the network will refuse is worse than one rejected up front. RFC 2812
allows a handful of punctuation characters in nicknames, but this keeps to the
conservative subset every network accepts.
"""

from __future__ import annotations

import re

MIN_LENGTH = 3
# Libera.Chat truncates nicknames beyond 16 characters.
MAX_LENGTH = 16

_VALID = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")

RULES = (
    f"{MIN_LENGTH}–{MAX_LENGTH} characters, starting with a letter. "
    "Letters, digits, hyphen and underscore only."
)


def validate(name: str) -> str | None:
    """Return an error message, or None when the name is usable."""
    name = name.strip()
    if not name:
        return "Enter a username."
    if len(name) < MIN_LENGTH:
        return f"Too short — at least {MIN_LENGTH} characters."
    if len(name) > MAX_LENGTH:
        return f"Too long — at most {MAX_LENGTH} characters."
    if not _VALID.match(name):
        if name[0].isdigit():
            return "Must start with a letter."
        return "Only letters, digits, hyphen and underscore."
    return None


def is_valid(name: str) -> bool:
    return validate(name) is None


def sanitise(name: str) -> str:
    """Coerce arbitrary text into something close to a usable name."""
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "", name.strip())
    cleaned = cleaned.lstrip("0123456789_-")
    return cleaned[:MAX_LENGTH]
