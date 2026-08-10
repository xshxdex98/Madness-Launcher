"""Glyphs for Qt sub-controls that stylesheets cannot draw.

QCheckBox::indicator, QComboBox::down-arrow and the QSpinBox buttons only
accept an image; CSS borders are ignored for them. Rather than ship binary
assets, the few glyphs needed are painted once at startup and cached on disk.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from .. import paths
from . import theme

_cache: dict[str, str] | None = None


def _new(width: int, height: int, scale: int) -> QPixmap:
    pm = QPixmap(width * scale, height * scale)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.transparent)
    return pm


def _painter(pm: QPixmap) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return p


def _check(scale: int) -> QPixmap:
    """Tick drawn dark, because it sits on the accent-filled indicator."""
    pm = _new(13, 13, scale)
    p = _painter(pm)
    pen = QPen(QColor("#14161A"))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(2.8, 6.8), QPointF(5.4, 9.4), QPointF(10.2, 3.6)])
    p.end()
    return pm


def _chevron(scale: int) -> QPixmap:
    pm = _new(11, 7, scale)
    p = _painter(pm)
    pen = QPen(QColor(theme.MUTED))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(1.5, 2.0), QPointF(5.5, 5.4), QPointF(9.5, 2.0)])
    p.end()
    return pm


def _triangle(scale: int, up: bool) -> QPixmap:
    pm = _new(9, 6, scale)
    p = _painter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.MUTED))
    pts = (
        [QPointF(4.5, 1.4), QPointF(8.0, 4.8), QPointF(1.0, 4.8)]
        if up
        else [QPointF(4.5, 4.8), QPointF(8.0, 1.4), QPointF(1.0, 1.4)]
    )
    p.drawPolygon(pts)
    p.end()
    return pm


def ensure_icons(scale: int = 2) -> dict[str, str]:
    """Paint the glyphs to PNG and return {name: stylesheet-safe path}.

    Must be called after a QApplication exists, since QPixmap needs one.
    """
    global _cache
    if _cache is not None:
        return _cache

    out_dir = paths.app_root() / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)

    glyphs = {
        "check": _check(scale),
        "chevron": _chevron(scale),
        "up": _triangle(scale, up=True),
        "down": _triangle(scale, up=False),
    }

    result: dict[str, str] = {}
    for name, pm in glyphs.items():
        target = out_dir / f"{name}.png"
        # Regenerate every run so a palette change is picked up.
        pm.save(str(target), "PNG")
        result[name] = target.as_posix()

    _cache = result
    return result
