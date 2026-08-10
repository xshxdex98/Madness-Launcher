"""Borrowing the game's own typeface for the launcher's display text.

Midtown Madness sets its menus in Gill Sans, and the font ships inside every
copy of the game. When a configured install has it, the launcher uses it for
headings so the shell feels like part of the game. Body text stays on the system
UI font, which stays legible at 12-13px in a way Gill Sans does not.

Nothing here is required: with no game configured, or a copy that omits the
fonts, the launcher falls back to its defaults.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

# Font files to look for in a game folder, in order of preference, mapped to
# the family they are expected to register.
CANDIDATES = (
    "GIL_____.TTF",  # Gill Sans MT, regular
    "GILB____.TTF",  # bold
)

_loaded: str | None = None


def load_display_font(search_roots: list[Path]) -> str | None:
    """Register the game's display font and return its family name.

    Returns None when no candidate is found, so callers keep their default.
    """
    global _loaded
    if _loaded is not None:
        return _loaded or None

    families: list[str] = []
    for root in search_roots:
        if not root or not root.is_dir():
            continue
        for name in CANDIDATES:
            path = _find(root, name)
            if path is None:
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                families.extend(QFontDatabase.applicationFontFamilies(font_id))
        if families:
            break

    _loaded = families[0] if families else ""
    return _loaded or None


def _find(root: Path, name: str) -> Path | None:
    direct = root / name
    if direct.is_file():
        return direct
    lowered = name.lower()
    try:
        for child in root.iterdir():
            if child.is_file() and child.name.lower() == lowered:
                return child
    except OSError:
        return None
    return None
