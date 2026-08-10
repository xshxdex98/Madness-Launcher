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
    """The sidebar's brand slot: the user's image, or a prompt to add one."""

    clicked = Signal()

    def __init__(self, max_height: int = 116):
        super().__init__()
        self.setObjectName("LogoArea")
        self.setCursor(Qt.PointingHandCursor)
        self._max_height = max_height
        self._source: QPixmap | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)

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
            # Word wrap makes QLabel size itself from its text, which collapses
            # the label to zero height when the text is empty and the content is
            # a pixmap. It is only wanted for the placeholder.
            self.label.setWordWrap(False)
            self.label.setText("")
            self.setToolTip("Click to change the logo")
            self._rescale()
        else:
            self._source = None
            self.setProperty("empty", True)
            self.label.setWordWrap(True)
            self.label.setPixmap(QPixmap())
            self.label.setMinimumHeight(0)
            self.label.setMaximumHeight(16777215)
            self.label.setText("Add a logo")
            self.setToolTip("Click to choose an image for the sidebar")
        # Re-evaluate the stylesheet, which keys off the `empty` property.
        self.style().unpolish(self)
        self.style().polish(self)
        return self._source is not None

    def has_logo(self) -> bool:
        """Whether an image is on show, whoever it came from."""
        return self._source is not None

    def _rescale(self) -> None:
        if self._source is None:
            return
        ratio = self.devicePixelRatioF() or 1.0
        available = max(self.width() - 12, 32)
        scaled = self._source.scaled(
            int(available * ratio),
            int(self._max_height * ratio),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.label.setPixmap(scaled)
        # Reserve exactly the height the image needs; without this the frame
        # keeps whatever height the placeholder text last asked for.
        height = int(scaled.height() / ratio)
        self.label.setMinimumHeight(height)
        self.label.setMaximumHeight(height)

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._rescale()

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class StatusDot(QLabel):
    """A coloured dot used for install/verification state."""

    COLORS = {
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
        color = QColor(self.COLORS.get(state, theme.FAINT))
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
