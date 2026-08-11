"""Small reusable pieces of the interface."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


class Card(QFrame):
    """A titled panel. Content goes into `body`."""

    def __init__(self, title: str = "", subtitle: str = "", inset: bool = False):
        super().__init__()
        self.setObjectName("InsetCard" if inset else "Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        if title:
            head = QVBoxLayout()
            head.setSpacing(3)
            label = QLabel(title)
            label.setObjectName("CardTitle")
            head.addWidget(label)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setObjectName("Faint")
                sub.setWordWrap(True)
                head.addWidget(sub)
            outer.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)


class LogoArea(QFrame):
    """The sidebar's brand slot: the user's image, or a prompt to add one.

    The image is painted to fit whatever rectangle the frame is given, rather
    than the frame being stretched to fit the image. Sized the other way round
    the logo spills out of its own slot as soon as the sidebar is short of
    room — and on a 620px-tall window, with six games and the community
    entries below it, the sidebar is about a hundred pixels short. What that
    looked like was a full-size logo clipped to a sliver.

    Asking for a height rather than fixing one also lets the slot grow with
    the window: the sidebar widens as the window does, and the logo follows.
    """

    clicked = Signal()

    PAD = 6
    # An upper bound on height as a fraction of the width available, so a tall
    # narrow image is held back instead of pushing the navigation off the
    # screen. Wide images are limited by the width and never reach this.
    MAX_ASPECT = 0.62
    # Below this there is no point drawing an image at all, so the frame stops
    # giving ground and the sidebar scrolls instead.
    MIN_HEIGHT = 30

    def __init__(self, max_height: int = 150):
        super().__init__()
        self.setObjectName("LogoArea")
        self.setCursor(Qt.PointingHandCursor)
        self._max_height = max_height
        self._source: QPixmap | None = None
        # Preferred rather than Fixed: Fixed makes Qt treat the size hint as a
        # hard minimum, so a sidebar short of room pushes the account block off
        # the bottom instead of trimming the logo. Preferred lets it give way,
        # and paintEvent fits the image to whatever it ends up with.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(self.PAD, self.PAD, self.PAD, self.PAD)
        layout.setSpacing(0)

        # Only ever holds the placeholder text. The image is painted directly,
        # because a QLabel sizes itself from its pixmap and that is the whole
        # problem being avoided here.
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self.set_logo(None)

    def set_logo(self, path: str | Path | None) -> bool:
        """Show an image, or the placeholder when it is missing or unreadable."""
        pixmap = QPixmap(str(path)) if path else QPixmap()
        if path and not pixmap.isNull():
            self._source = pixmap
            self.setProperty("empty", False)
            self.label.setWordWrap(False)
            self.label.setText("")
            self.label.hide()
            self.setToolTip("Click to change the logo")
        else:
            self._source = None
            self.setProperty("empty", True)
            self.label.setWordWrap(True)
            self.label.setText("Add a logo")
            self.label.show()
            self.setToolTip("Click to choose an image for the sidebar")
        # Re-evaluate the stylesheet, which keys off the `empty` property.
        self.style().unpolish(self)
        self.style().polish(self)
        # Re-fit for the size already in hand, so swapping the image does not
        # wait on a window resize to take the right amount of room.
        self.fit(self.width() or self._max_height, self._max_height)
        return self._source is not None

    def has_logo(self) -> bool:
        """Whether an image is on show, whoever it came from."""
        return self._source is not None

    # -- sizing ------------------------------------------------------------

    def fit(self, width: int, max_height: int) -> None:
        """Size the slot for a frame of `width`, within `max_height`.

        Driven from outside rather than through sizeHint. A hint that depends
        on the widget's own width has to be recomputed as the layout settles,
        and Qt caches the parent's hint from the first pass — which left the
        header stuck at the height it had before the image was known. The
        sidebar knows both numbers up front, so it just says.
        """
        self._max_height = max(self.MIN_HEIGHT, int(max_height))
        if self._source is None:
            # The placeholder sizes itself from its text, as a label should.
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            return
        self.setFixedHeight(self._content_size(width)[1] + 2 * self.PAD)
        self.update()

    def _content_size(self, width: int) -> tuple[int, int]:
        """The size to draw the image at inside a frame of the given width."""
        source = self._source
        if source is None or source.isNull() or source.height() <= 0:
            return 0, 0
        inner = max(width - 2 * self.PAD, 1)
        # Never enlarged past its own resolution: a 64px logo blown up to fill
        # a wide sidebar looks worse than a small sharp one.
        cap = max(
            min(
                self._max_height - 2 * self.PAD,
                round(inner * self.MAX_ASPECT),
                source.height(),
            ),
            1,
        )
        w = min(inner, source.width())
        h = round(w * source.height() / source.width())
        if h > cap:
            h = cap
            w = round(h * source.width() / source.height())
        return max(w, 1), max(h, 1)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        super().paintEvent(event)
        source = self._source
        if source is None or source.isNull():
            return

        width, height = self._content_size(self.width())
        # The frame can still end up shorter than it asked for. Fit the image
        # to what is actually there rather than drawing over the edges.
        room = self.height() - 2 * self.PAD
        if room < height and height > 0:
            width = max(round(width * room / height), 1)
            height = max(room, 1)
        if width <= 0 or height <= 0:
            return

        ratio = self.devicePixelRatioF() or 1.0
        scaled = source.scaled(
            round(width * ratio),
            round(height * ratio),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        painter = QPainter(self)
        painter.drawPixmap(
            round((self.width() - scaled.width() / ratio) / 2),
            round((self.height() - scaled.height() / ratio) / 2),
            scaled,
        )
        painter.end()

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class StatusDot(QLabel):
    """A coloured dot used for install/verification state."""

    # Looked up when the dot is painted, not when the class is defined. As a
    # class attribute this froze whatever the palette happened to be at import
    # and the dots then kept the old colours through a theme change.
    @staticmethod
    def colors() -> dict[str, str]:
        return {
            "good": theme.GOOD,
            "warn": theme.WARN,
            "bad": theme.BAD,
            "idle": theme.FAINT,
        }

    def __init__(self, state: str = "idle", size: int = 8):
        super().__init__()
        self._size = size
        self._state = state
        self.setFixedSize(size, size)
        self.set_state(state)

    @property
    def state(self) -> str:
        """The state last set. The dot is a pixmap, so it cannot be read back."""
        return self._state

    def set_state(self, state: str) -> None:
        self._state = state
        color = QColor(self.colors().get(state, theme.FAINT))
        pm = QPixmap(self._size, self._size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, self._size, self._size)
        painter.end()
        self.setPixmap(pm)


class Badge(QLabel):
    """A small pill for short status words."""

    def __init__(self, text: str = "", tone: str = "muted"):
        super().__init__(text)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        colors = {
            "good": theme.GOOD,
            "warn": theme.WARN,
            "bad": theme.BAD,
            "muted": theme.MUTED,
        }
        color = colors.get(tone, theme.MUTED)
        bg = theme._mix(color, theme.BG, 0.82)
        self.setStyleSheet(
            f"color: {color}; background: {bg}; border: 1px solid "
            f"{theme._mix(color, theme.BG, 0.6)}; border-radius: 9px; "
            f"padding: 2px 9px; font-size: 11px; font-weight: 600;"
        )


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class GroupHeading(QLabel):
    def __init__(self, text: str):
        super().__init__(text.upper())
        self.setObjectName("GroupHeading")


class FieldRow(QWidget):
    """A labelled row: description on the left, control on the right."""

    def __init__(self, label: str, control: QWidget, help_text: str = ""):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(label)
        text_col.addWidget(name)
        if help_text:
            hint = QLabel(help_text)
            hint.setObjectName("Faint")
            hint.setWordWrap(True)
            text_col.addWidget(hint)
        layout.addLayout(text_col, 1)

        control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.control = control


def scrollable(inner: QWidget) -> QScrollArea:
    """Wrap a widget in a frameless, vertically scrolling area."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


def column(*, spacing: int = 14, margins: tuple[int, int, int, int] = (0, 0, 0, 0)):
    """A QWidget with a preconfigured vertical layout, returned as a pair."""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return w, layout
