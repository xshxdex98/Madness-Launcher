"""The library: a front door for the launcher.

Before this, opening the launcher dropped you straight into whichever game
happened to be configured first, with no sense of what else was there. The
library is a grid of cards — one per game, with artwork, status and a Play
button — so there is somewhere for a first impression to happen and somewhere
for artwork to live.

Cards paint their own artwork from the game's accent unless the user has
supplied an image, which keeps the launcher asset-free out of the box while
still rewarding anyone who drops a screenshot in.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import branding
from ..config import Config
from ..detect import identify_as
from ..games.base import GameDef
from ..games.registry import GAMES
from . import gameart, theme
from .widgets import StatusDot, scrollable

# Cards stretch to fill the row rather than sitting at a fixed size: a fixed
# width leaves a ragged band of dead space on the right at most window sizes.
CARD_WIDTH = 296  # the minimum; the column count is derived from it
ART_HEIGHT = 150
BADGE = 44  # the game's own icon, drawn on the art panel
GRID_SPACING = 18

# Status text under each title, keyed by the same states the sidebar dots use.
STATUS_TEXT = {
    "good": "Ready to play",
    "warn": "Needs attention",
    "bad": "Folder not usable",
    "idle": "Not set up",
}


def _mix(colour: str, other: str, amount: float) -> QColor:
    """Blend two colours; `amount` is how much of `other` to take."""
    a, b = QColor(colour), QColor(other)
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


class CardArt(QLabel):
    """The picture at the top of a card.

    Falls back to a painted panel built from the game's accent, so a game with
    no artwork still looks deliberate rather than blank.
    """

    def __init__(self, game: GameDef):
        super().__init__()
        self.game = game
        self._custom: QPixmap | None = None
        self._badge: QPixmap | None = None
        self.setFixedHeight(ART_HEIGHT)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def load(self, root: str = "") -> None:
        """Pick up the user's artwork and the game's own icon, if any."""
        stored = branding.stored_hero(self.game.id)
        pixmap = QPixmap(str(stored)) if stored is not None else QPixmap()
        self._custom = None if pixmap.isNull() else pixmap

        # The real icon out of the executable, at the largest size it stores.
        icon = gameart.icon_for(self.game, root or None)
        badge = icon.pixmap(QSize(BADGE, BADGE)) if icon is not None else None
        self._badge = badge if badge is not None and not badge.isNull() else None
        self.update()

    def has_custom(self) -> bool:
        return self._custom is not None

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.TextAntialiasing)

        rect = QRectF(self.rect())
        # Round only the top corners; the bottom meets the card's info strip.
        path = QPainterPath()
        radius = 9.0
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + radius)
        path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        painter.setClipPath(path)

        if self._custom is not None:
            self._paint_photo(painter, rect)
        else:
            self._paint_generated(painter, rect)
        self._paint_badge(painter, rect)
        painter.end()

    def _paint_badge(self, painter: QPainter, rect: QRectF) -> None:
        """The game's own icon, bottom-right, on a soft plate so it reads on
        light artwork as well as dark."""
        if self._badge is None:
            return
        size = BADGE
        x = rect.right() - size - 14
        y = rect.bottom() - size - 12
        plate = QRectF(x - 7, y - 7, size + 14, size + 14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(8, 11, 17, 120))
        painter.drawRoundedRect(plate, 9, 9)
        painter.drawPixmap(QRectF(x, y, size, size), self._badge,
                           QRectF(self._badge.rect()))

    def _paint_photo(self, painter: QPainter, rect: QRectF) -> None:
        """Cover-crop the user's image, then darken its foot for the caption."""
        source = self._custom
        scaled = source.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        x = (scaled.width() - self.width()) // 2
        y = (scaled.height() - self.height()) // 2
        painter.drawPixmap(
            self.rect(), scaled, QRect(x, y, self.width(), self.height())
        )

        shade = QLinearGradient(
            QPointF(0, rect.height() * 0.45), QPointF(0, rect.height())
        )
        shade.setColorAt(0.0, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, QColor(0, 0, 0, 150))
        painter.fillRect(rect, shade)

    def _paint_generated(self, painter: QPainter, rect: QRectF) -> None:
        accent = self.game.accent
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, _mix(accent, theme.BG, 0.42))
        gradient.setColorAt(1.0, _mix(accent, theme.BG, 0.86))
        painter.fillRect(rect, gradient)

        # A pair of slanted bands, faint enough to read as texture rather than
        # decoration. Speed lines, roughly.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 12))
        for offset in (-0.15, 0.28):
            band = QPainterPath()
            left = rect.width() * offset
            band.moveTo(left, rect.height())
            band.lineTo(left + rect.height() * 0.62, 0)
            band.lineTo(left + rect.height() * 0.62 + 44, 0)
            band.lineTo(left + 44, rect.height())
            band.closeSubpath()
            painter.drawPath(band)

        # The community shorthand — MM1, MTM2, MCM2 — as the mark.
        mark = QFont(theme.DISPLAY_FONT, 40)
        mark.setBold(True)
        mark.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        painter.setFont(mark)
        painter.setPen(QColor(255, 255, 255, 44))
        painter.drawText(
            rect.adjusted(16, 0, -16, -8), Qt.AlignLeft | Qt.AlignVCenter,
            self.game.id.upper(),
        )

        strip = QFont(theme.FONT, 8)
        strip.setLetterSpacing(QFont.AbsoluteSpacing, 2.6)
        painter.setFont(strip)
        painter.setPen(QColor(255, 255, 255, 120))
        painter.drawText(
            rect.adjusted(18, 0, -18, -10),
            Qt.AlignLeft | Qt.AlignBottom,
            self.game.developer.upper(),
        )


class GameCard(QFrame):
    """One game in the grid."""

    opened = Signal(str)
    played = Signal(str)
    artwork_changed = Signal(str)

    def __init__(self, game: GameDef):
        super().__init__()
        self.game = game
        self._root = ""
        self.setObjectName("GameCard")
        self.setMinimumWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.art = CardArt(game)
        layout.addWidget(self.art)

        info = QWidget()
        info.setObjectName("GameCardInfo")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(15, 12, 15, 13)
        info_layout.setSpacing(3)

        title = QLabel(game.title)
        title.setObjectName("CardTitle")
        info_layout.addWidget(title)

        meta = QLabel(f"{game.year}  ·  {game.developer}")
        meta.setObjectName("Faint")
        info_layout.addWidget(meta)

        info_layout.addSpacing(8)

        bottom = QHBoxLayout()
        bottom.setSpacing(7)

        self.dot = StatusDot("idle")
        bottom.addWidget(self.dot, 0, Qt.AlignVCenter)

        self.status = QLabel(STATUS_TEXT["idle"])
        self.status.setObjectName("Muted")
        bottom.addWidget(self.status, 0, Qt.AlignVCenter)
        bottom.addStretch(1)

        self.action = QPushButton("Set up")
        self.action.setObjectName("CardPlay")
        self.action.setCursor(Qt.PointingHandCursor)
        self.action.clicked.connect(self._on_action)
        bottom.addWidget(self.action, 0, Qt.AlignVCenter)

        info_layout.addLayout(bottom)
        layout.addWidget(info)

        # Accent lives on the card, not the application stylesheet — switching
        # games must not trigger a global restyle.
        # Only a set-up game gets the accent-filled button; "Set up" stays
        # neutral so the colour means "this one is ready to go".
        self.setStyleSheet(
            f'#GameCard #CardPlay[ready="true"] {{ background: {game.accent}; }}'
            f'#GameCard #CardPlay[ready="true"]:hover {{'
            f" background: {_mix(game.accent, '#FFFFFF', 0.18).name()}; }}"
            f"#GameCard:hover {{ border-color: {game.accent}; }}"
        )

    # -- state -----------------------------------------------------------

    def set_state(self, state: str) -> None:
        self.dot.set_state(state)
        self.status.setText(STATUS_TEXT.get(state, STATUS_TEXT["idle"]))
        playable = state in ("good", "warn")
        self.action.setText("Play" if playable else "Set up")
        self.action.setProperty("ready", playable)
        self.action.style().unpolish(self.action)
        self.action.style().polish(self.action)
        self.setToolTip(
            f"{self.game.title} — {self.game.subtitle}"
            if self.game.subtitle
            else self.game.title
        )

    def reload_art(self, root: str = "") -> None:
        self._root = root
        self.art.load(root)

    def _on_action(self) -> None:
        if self.action.text() == "Play":
            self.played.emit(self.game.id)
        else:
            self.opened.emit(self.game.id)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.opened.emit(self.game.id)
        super().mouseReleaseEvent(event)

    # -- artwork ---------------------------------------------------------

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.opened.emit(self.game.id))
        menu.addSeparator()
        menu.addAction("Set artwork…", self._choose_art)
        remove = menu.addAction("Remove artwork", self._clear_art)
        remove.setEnabled(self.art.has_custom())
        menu.exec(self.mapToGlobal(pos))

    def _choose_art(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"Artwork for {self.game.title}", "", branding.FILE_FILTER
        )
        if not chosen:
            return
        try:
            branding.install_hero(Path(chosen), self.game.id)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Could not use that image", str(exc))
            return
        self._reload_own_art()
        if not self.art.has_custom():
            # Qt could not decode it; do not leave an unusable file behind.
            branding.clear_hero(self.game.id)
            QMessageBox.warning(
                self,
                "Could not use that image",
                f"{Path(chosen).name} could not be decoded as an image.",
            )
            return
        self.artwork_changed.emit(self.game.id)

    def _clear_art(self) -> None:
        branding.clear_hero(self.game.id)
        self._reload_own_art()
        self.artwork_changed.emit(self.game.id)

    def _reload_own_art(self) -> None:
        """Reload keeping whatever install root the card was last given."""
        self.art.load(self._root)


class LibraryPage(QWidget):
    """The grid of game cards, reflowing to the window width."""

    opened = Signal(str)
    played = Signal(str)
    status_message = Signal(str)

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._columns = 0
        self._cards: list[GameCard] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(34, 28, 34, 26)
        layout.setSpacing(6)

        title = QLabel("Library")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        layout.addSpacing(20)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(GRID_SPACING)
        self.grid.setVerticalSpacing(GRID_SPACING)
        self.grid.setAlignment(Qt.AlignTop)
        layout.addLayout(self.grid)

        for game in GAMES:
            card = GameCard(game)
            card.opened.connect(self.opened)
            card.played.connect(self.played)
            card.artwork_changed.connect(self._on_artwork_changed)
            self._cards.append(card)

        hint = QLabel(
            "Right-click a card to set its artwork. Click a card to open its "
            "options and mods."
        )
        hint.setObjectName("Faint")
        # Word-wrapped so a long line cannot widen the page past its scroll
        # viewport, which would push the right-hand card off the edge.
        hint.setWordWrap(True)
        layout.addSpacing(20)
        layout.addWidget(hint)
        layout.addStretch(1)

        self._host = host
        outer.addWidget(scrollable(host))
        self._reflow(force=True)

    # -- layout ----------------------------------------------------------

    def _available_width(self) -> int:
        # Card area is the page minus its 34px margins, less the scrollbar.
        return max(CARD_WIDTH, self.width() - 68 - 14)

    def _reflow(self, force: bool = False) -> None:
        columns = max(
            1, (self._available_width() + GRID_SPACING) // (CARD_WIDTH + GRID_SPACING)
        )
        columns = min(columns, max(1, len(self._cards)))
        if columns == self._columns and not force:
            return
        self._columns = columns

        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self._cards):
            self.grid.addWidget(card, index // columns, index % columns)

        # Equal stretch across the live columns so the row fills the width;
        # clear the rest or a stale stretch keeps reserving space.
        for column in range(max(columns, len(self._cards))):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._reflow()

    # -- state -----------------------------------------------------------

    def refresh(self) -> None:
        """Re-read install state for every card. Cheap: no page rebuilds."""
        ready = 0
        for card in self._cards:
            state = self._state_for(card.game)
            if state in ("good", "warn"):
                ready += 1
            card.set_state(state)
            install = self.config.install(card.game.id)
            card.reload_art(install.path if install else "")

        total = len(self._cards)
        if ready == 0:
            self.summary.setText(
                f"{total} games supported — none set up yet. "
                "Pick one to point the launcher at its folder."
            )
        elif ready == total:
            self.summary.setText(f"All {total} games set up and ready.")
        else:
            self.summary.setText(f"{ready} of {total} games set up.")

    def _state_for(self, game: GameDef) -> str:
        install = self.config.install(game.id)
        if not install or not install.path:
            return "idle"
        result = identify_as(Path(install.path), game)
        if result is None or not result.playable:
            return "bad"
        if result.missing_data or result.absent_with_residue:
            return "warn"
        return "good"

    def _on_artwork_changed(self, game_id: str) -> None:
        self.status_message.emit("Artwork updated")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(CARD_WIDTH * 3, 700)
