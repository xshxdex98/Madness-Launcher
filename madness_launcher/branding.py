"""The user's own logo for the sidebar.

The chosen image is copied into the launcher's data folder rather than
referenced in place, so the logo survives the original being moved, renamed or
deleted — a launcher that loses its branding because a file moved would be a
silly way to fail.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import paths

# Formats Qt can decode without any extra image plugins installed.
SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico", ".svg")

FILE_FILTER = (
    "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.ico *.svg);;All files (*)"
)


def branding_dir() -> Path:
    return paths.app_root() / "branding"


def stored_image(stem: str) -> Path | None:
    """An installed image by stem, if there is one."""
    folder = branding_dir()
    if not folder.is_dir():
        return None
    for child in sorted(folder.iterdir()):
        if child.is_file() and child.stem == stem:
            return child
    return None


def stored_logo() -> Path | None:
    """The installed sidebar logo, if there is one."""
    return stored_image("logo")


def hero_stem(game_id: str) -> str:
    return f"hero-{game_id}"


def stored_hero(game_id: str) -> Path | None:
    """Artwork the user has chosen for a game's library card."""
    return stored_image(hero_stem(game_id))


def install_logo(source: Path) -> Path:
    """Copy an image in as the launcher's sidebar logo."""
    return install_image(source, "logo")


def install_hero(source: Path, game_id: str) -> Path:
    """Copy an image in as a game's library artwork."""
    return install_image(source, hero_stem(game_id))


def clear_hero(game_id: str) -> None:
    clear_image(hero_stem(game_id))


def install_image(source: Path, stem: str) -> Path:
    """Copy an image into the launcher's own folder under a given stem."""
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"{source} is not a file.")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"{source.suffix or 'That file type'} is not a supported image "
            "format. Use PNG, JPEG, BMP, GIF, WebP, ICO or SVG."
        )

    clear_image(stem)
    folder = branding_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stem}{source.suffix.lower()}"
    shutil.copy2(source, target)
    return target


def clear_logo() -> None:
    clear_image("logo")


def clear_image(stem: str) -> None:
    folder = branding_dir()
    if not folder.is_dir():
        return
    for child in folder.iterdir():
        if child.is_file() and child.stem == stem:
            child.unlink(missing_ok=True)
