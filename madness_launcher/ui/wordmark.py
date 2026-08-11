"""The launcher's own wordmark, painted rather than shipped.

The sidebar's logo slot used to start life as a dashed "Add a logo" box, which
is the first thing anyone sees and makes a fresh install look unfinished. This
draws a real mark to sit there instead — still replaceable, but a sensible
default rather than an empty prompt.

Painted at runtime for the same reason the UI glyphs are: no binary assets to
keep in the repository, and it picks up whichever display face is available.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from .. import paths
from . import theme

WIDTH = 208
HEIGHT = 62


def _draw(scale: int, accent: str) -> QPixmap:
    pixmap = QPixmap(WIDTH * scale, HEIGHT * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    # MADNESS, wide-tracked, in the display face when the game's font is loaded.
    title = QFont(theme.DISPLAY_FONT, 21)
    title.setBold(True)
    title.setLetterSpacing(QFont.AbsoluteSpacing, 4.0)
    painter.setFont(title)
    painter.setPen(QColor(theme.TEXT))
    painter.drawText(
        QRectF(0, 2, WIDTH, 30), Qt.AlignLeft | Qt.AlignVCenter, "MADNESS"
    )

    # A short accent rule under the word, the one spot of colour.
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawRoundedRect(QRectF(1, 35, 34, 3), 1.5, 1.5)

    sub = QFont(theme.FONT, 8)
    sub.setLetterSpacing(QFont.AbsoluteSpacing, 3.4)
    painter.setFont(sub)
    painter.setPen(QColor(theme.MUTED))
    painter.drawText(
        QRectF(2, 42, WIDTH, 16), Qt.AlignLeft | Qt.AlignVCenter, "LAUNCHER"
    )
    painter.end()
    return pixmap


def default_logo(accent: str = "", scale: int = 2) -> Path:
    """Paint the wordmark to disk and return its path.

    Rewritten on demand so a change of display font or palette is picked up.
    The accent defaults to the live one rather than to the shipped one: as a
    default argument the latter is evaluated at import, which left the
    wordmark wearing the stock orange under every custom theme.
    """
    target = paths.app_root() / "branding" / "default-logo.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    _draw(scale, accent or theme.ACCENT).save(str(target), "PNG")
    return target
