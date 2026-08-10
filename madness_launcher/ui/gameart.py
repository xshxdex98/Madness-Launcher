"""Per-game marks: the real icon where possible, a painted one otherwise.

The games carry their own icons in their executables, which beats anything
drawn here — it is the artwork the game shipped with. But the sidebar lists
every supported game whether or not it has been set up, and an unconfigured
game has no executable to read, so there has to be a fallback that does not
look like a missing image.

Icons are decoded straight from memory and cached for the session. No disk
cache: extraction is a single read of an already-small executable, and a cache
on disk would only add a staleness problem to solve.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPixmap,
    QTransform,
)

from .. import exeicon
from ..games.base import GameDef
from . import theme

# game id -> QIcon, or None once extraction has been tried and failed.
_cache: dict[str, QIcon | None] = {}


def clear_cache() -> None:
    """Forget extracted icons — call when an install path changes."""
    _cache.clear()


def _extract(game: GameDef, root: Path) -> QIcon | None:
    """Read the game's icon out of its executable."""
    names: list[str] = []
    # An explicit choice wins: a portable build's launcher wrapper often has a
    # generic icon while the real binary beside it has the game's own.
    if game.icon_exe:
        names.append(game.icon_exe)
    names.extend(t.filename for t in game.exe_targets)

    seen: set[str] = set()
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        exe = root / name
        if not exe.is_file():
            continue
        data = exeicon.extract_ico(exe)
        if not data:
            continue
        icon = _icon_from_ico(data)
        if icon is not None:
            return icon
    return None


def _icon_from_ico(data: bytes) -> QIcon | None:
    """Build a QIcon holding every size stored in the .ico.

    Loading the container into a single QPixmap would keep only one frame and
    leave Qt scaling it; reading each frame lets it pick the right one for
    whatever size is asked for.
    """
    # The QByteArray must outlive the QBuffer that wraps it. Passing it inline
    # lets Python collect it while Qt is still reading through the pointer,
    # which crashes rather than failing.
    payload = QByteArray(data)
    buffer = QBuffer(payload)
    buffer.open(QBuffer.ReadOnly)
    reader = QImageReader(buffer, b"ICO")
    icon = QIcon()
    added = 0
    for index in range(max(1, reader.imageCount())):
        if not reader.jumpToImage(index):
            break
        image = reader.read()
        if image.isNull():
            continue
        icon.addPixmap(QPixmap.fromImage(image))
        added += 1
    buffer.close()
    return icon if added else None


def _shape_path(shape: str, rect: QRectF) -> QPainterPath:
    """A crude silhouette — a car, a truck or a bike — sized to `rect`.

    Read at 16-20px, so these are deliberately blunt: detail would turn to mud.
    """
    path = QPainterPath()
    width, height = rect.width(), rect.height()

    def point(fx: float, fy: float) -> QPointF:
        return QPointF(rect.left() + width * fx, rect.top() + height * fy)

    if shape == "truck":
        # Tall cab, big wheels.
        body = QPainterPath()
        body.addRoundedRect(
            QRectF(point(0.10, 0.30), point(0.90, 0.62)), width * 0.06, width * 0.06
        )
        cab = QPainterPath()
        cab.addRoundedRect(
            QRectF(point(0.24, 0.14), point(0.66, 0.34)), width * 0.05, width * 0.05
        )
        path = body.united(cab)
        for centre in (0.26, 0.74):
            wheel = QPainterPath()
            wheel.addEllipse(point(centre, 0.70), width * 0.17, width * 0.17)
            path = path.united(wheel)
        return path

    if shape == "bike":
        # Two wheels and a frame line, drawn as a filled arc pair.
        for centre in (0.22, 0.78):
            wheel = QPainterPath()
            wheel.addEllipse(point(centre, 0.66), width * 0.20, width * 0.20)
            inner = QPainterPath()
            inner.addEllipse(point(centre, 0.66), width * 0.11, width * 0.11)
            path = path.united(wheel.subtracted(inner))
        frame = QPainterPath()
        frame.moveTo(point(0.22, 0.66))
        frame.lineTo(point(0.44, 0.30))
        frame.lineTo(point(0.66, 0.30))
        frame.lineTo(point(0.78, 0.66))
        frame.lineTo(point(0.62, 0.66))
        frame.lineTo(point(0.52, 0.42))
        frame.lineTo(point(0.36, 0.70))
        frame.closeSubpath()
        return path.united(frame)

    # Default: a low car.
    body = QPainterPath()
    body.moveTo(point(0.06, 0.62))
    body.lineTo(point(0.14, 0.44))
    body.lineTo(point(0.34, 0.42))
    body.lineTo(point(0.46, 0.26))
    body.lineTo(point(0.68, 0.26))
    body.lineTo(point(0.78, 0.44))
    body.lineTo(point(0.94, 0.50))
    body.lineTo(point(0.94, 0.62))
    body.closeSubpath()
    path = body
    for centre in (0.28, 0.74):
        wheel = QPainterPath()
        wheel.addEllipse(point(centre, 0.66), width * 0.14, width * 0.14)
        path = path.united(wheel)
    return path


def painted_mark(game: GameDef, size: int, colour: str | None = None) -> QPixmap:
    """The fallback mark for a game with no executable to read."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(colour or theme.FAINT))
    painter.drawPath(_shape_path(game.icon_shape, QRectF(0, 0, size, size)))
    painter.end()
    return pixmap


def nav_glyph(name: str, size: int = 18, colour: str | None = None) -> QPixmap:
    """A mark for the sidebar rows that are not games.

    Without these, Library, Chat Room and Settings would sit flush against the
    edge while the game rows are indented by their icons, and the column of
    labels would not line up.
    """
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    ink = QColor(colour or theme.MUTED)
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink)
    unit = size / 18.0

    if name == "library":
        # Four rounded tiles: a shelf of cards.
        for row in (0, 1):
            for column in (0, 1):
                painter.drawRoundedRect(
                    QRectF(
                        (2.5 + column * 7.0) * unit,
                        (2.5 + row * 7.0) * unit,
                        6.0 * unit,
                        6.0 * unit,
                    ),
                    1.4 * unit,
                    1.4 * unit,
                )
    elif name == "chat":
        # A speech bubble with a tail.
        bubble = QPainterPath()
        bubble.addRoundedRect(
            QRectF(2.0 * unit, 3.0 * unit, 14.0 * unit, 10.0 * unit),
            3.0 * unit,
            3.0 * unit,
        )
        tail = QPainterPath()
        tail.moveTo(QPointF(5.5 * unit, 12.0 * unit))
        tail.lineTo(QPointF(5.5 * unit, 16.5 * unit))
        tail.lineTo(QPointF(10.0 * unit, 12.0 * unit))
        tail.closeSubpath()
        painter.drawPath(bubble.united(tail))
    elif name == "news":
        # A folded newspaper: a sheet with a masthead block and text lines,
        # and a second sheet peeking out behind it.
        painter.setBrush(ink.darker(160))
        painter.drawRoundedRect(
            QRectF(1.5 * unit, 4.5 * unit, 13.0 * unit, 11.0 * unit),
            1.4 * unit,
            1.4 * unit,
        )
        painter.setBrush(ink)
        sheet = QPainterPath()
        sheet.addRoundedRect(
            QRectF(3.5 * unit, 2.5 * unit, 13.0 * unit, 13.0 * unit),
            1.6 * unit,
            1.6 * unit,
        )
        # Knocked out of the sheet rather than drawn over it, so the glyph
        # stays readable against any sidebar state.
        masthead = QPainterPath()
        masthead.addRoundedRect(
            QRectF(5.2 * unit, 4.4 * unit, 5.2 * unit, 4.0 * unit),
            0.6 * unit,
            0.6 * unit,
        )
        sheet = sheet.subtracted(masthead)
        for index in range(3):
            line = QPainterPath()
            line.addRoundedRect(
                QRectF(
                    5.2 * unit,
                    (9.6 + index * 1.9) * unit,
                    9.6 * unit if index < 2 else 6.4 * unit,
                    1.0 * unit,
                ),
                0.5 * unit,
                0.5 * unit,
            )
            sheet = sheet.subtracted(line)
        right = QPainterPath()
        right.addRoundedRect(
            QRectF(11.2 * unit, 4.4 * unit, 3.6 * unit, 4.0 * unit),
            0.6 * unit,
            0.6 * unit,
        )
        painter.drawPath(sheet.subtracted(right))
    elif name == "settings":
        # A cog: a ring with teeth, hollowed out.
        cog = QPainterPath()
        cog.addEllipse(QPointF(9 * unit, 9 * unit), 6.6 * unit, 6.6 * unit)
        tooth = QPainterPath()
        tooth.addRoundedRect(
            QRectF(7.8 * unit, 0.9 * unit, 2.4 * unit, 4.0 * unit),
            0.8 * unit,
            0.8 * unit,
        )
        for index in range(8):
            rotate = QTransform()
            rotate.translate(9 * unit, 9 * unit)
            rotate.rotate(index * 45)
            rotate.translate(-9 * unit, -9 * unit)
            cog = cog.united(rotate.map(tooth))
        hole = QPainterPath()
        hole.addEllipse(QPointF(9 * unit, 9 * unit), 2.6 * unit, 2.6 * unit)
        painter.drawPath(cog.subtracted(hole))
    painter.end()
    return pixmap


def icon_for(game: GameDef, root: Path | str | None) -> QIcon | None:
    """The game's own icon, or None when there is no executable to read it from."""
    if game.id in _cache:
        return _cache[game.id]
    icon: QIcon | None = None
    if root:
        folder = Path(root)
        if folder.is_dir():
            try:
                icon = _extract(game, folder)
            except Exception:
                # A game's icon is never worth failing a window over.
                icon = None
    _cache[game.id] = icon
    return icon


def mark(game: GameDef, root: Path | str | None, size: int) -> QPixmap:
    """The best available mark for a game at `size`: real icon, else painted."""
    icon = icon_for(game, root)
    if icon is not None:
        pixmap = icon.pixmap(QSize(size, size))
        if not pixmap.isNull():
            return pixmap
    return painted_mark(game, size)
