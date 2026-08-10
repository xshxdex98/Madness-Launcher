"""The Overview tab: what the game is, who made it, and a video backdrop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..games.base import GameDef
from . import theme
from .video import FILE_FILTER, MULTIMEDIA_AVAILABLE, VideoBackground
from .widgets import scrollable


class OverviewPage(QWidget):
    """Game description and facts, over an optional looping video."""

    video_changed = Signal(str)  # new path, or "" when cleared

    def __init__(self, game: GameDef, video_path: str = ""):
        super().__init__()
        self.game = game
        self._video_path = ""
        self._video_error = False

        # The backdrop is a plain child widget sized to fill the page; the
        # content sits on top of it as a sibling, raised.
        self.backdrop = VideoBackground(accent=game.accent)
        self.backdrop.setParent(self)
        self.backdrop.error.connect(self._on_video_error)
        self.backdrop.state_changed.connect(self._sync_controls)

        self.content = QWidget(self)
        self.content.setAttribute(Qt.WA_TranslucentBackground)
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(scrollable(self._build_body()))

        self.set_video(video_path, announce=False)

    # -- layout ----------------------------------------------------------

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.backdrop.setGeometry(self.rect())
        self.content.setGeometry(self.rect())
        self.backdrop.lower()
        self.content.raise_()

    def _build_body(self) -> QWidget:
        body = QWidget()
        body.setAttribute(Qt.WA_TranslucentBackground)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 10, 18, 24)
        layout.setSpacing(20)

        header = QLabel(self.game.title)
        header.setObjectName("OverviewTitle")
        layout.addWidget(header)

        tagline = QLabel(self.game.subtitle)
        tagline.setObjectName("OverviewTagline")
        tagline.setWordWrap(True)
        layout.addWidget(tagline)

        layout.addWidget(self._build_facts())

        if self.game.description:
            for paragraph in self.game.description.split("\n\n"):
                text = QLabel(paragraph.strip())
                text.setObjectName("OverviewBody")
                text.setWordWrap(True)
                text.setMaximumWidth(760)
                layout.addWidget(text)

        layout.addSpacing(4)
        layout.addWidget(self._build_video_controls())
        layout.addStretch(1)
        return body

    # Facts wrap onto further rows rather than running off the edge; a game
    # with a long fact list would otherwise push the last columns out of view.
    FACT_COLUMNS = 4

    def _build_facts(self) -> QWidget:
        host = QWidget()
        host.setAttribute(Qt.WA_TranslucentBackground)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(34)
        grid.setVerticalSpacing(6)

        for index, (key, value) in enumerate(self.game.facts()):
            row, column = divmod(index, self.FACT_COLUMNS)
            label = QLabel(key.upper())
            label.setObjectName("FactKey")
            grid.addWidget(label, row * 3, column, Qt.AlignLeft | Qt.AlignBottom)

            val = QLabel(value)
            val.setObjectName("FactValue")
            grid.addWidget(val, row * 3 + 1, column, Qt.AlignLeft | Qt.AlignTop)

            if column == 0 and row:
                grid.setRowMinimumHeight(row * 3 - 1, 14)

        grid.setColumnStretch(self.FACT_COLUMNS, 1)
        return host

    def _build_video_controls(self) -> QWidget:
        host = QWidget()
        host.setAttribute(Qt.WA_TranslucentBackground)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)

        self.choose_button = QPushButton()
        self.choose_button.setObjectName("Ghost")
        self.choose_button.clicked.connect(self._choose_video)
        row.addWidget(self.choose_button)

        self.playpause_button = QPushButton("Pause")
        self.playpause_button.setObjectName("Ghost")
        self.playpause_button.clicked.connect(self._toggle_play)
        row.addWidget(self.playpause_button)

        self.sound_button = QPushButton("Unmute")
        self.sound_button.setObjectName("Ghost")
        self.sound_button.clicked.connect(self._toggle_sound)
        row.addWidget(self.sound_button)

        self.clear_button = QPushButton("Remove video")
        self.clear_button.setObjectName("Danger")
        self.clear_button.clicked.connect(self._clear_video)
        row.addWidget(self.clear_button)

        row.addStretch(1)

        self.video_note = QLabel()
        self.video_note.setObjectName("Faint")
        self.video_note.setWordWrap(True)
        row.addWidget(self.video_note, 1)

        return host

    # -- video -----------------------------------------------------------

    def set_video(self, path: str, announce: bool = True) -> None:
        self._video_error = False
        self.video_note.setStyleSheet("")
        ok = self.backdrop.set_source(path or None)
        self._video_path = path if ok else ""
        self._sync_controls(requested=path)
        if announce:
            self.video_changed.emit(self._video_path)

    def _sync_controls(self, requested: str = "") -> None:
        has_video = bool(self._video_path)
        self.choose_button.setText(
            "Change video…" if has_video else "Add background video…"
        )
        for button in (self.playpause_button, self.sound_button, self.clear_button):
            button.setVisible(has_video)
        self.playpause_button.setText("Pause" if self.backdrop.playing else "Play")
        self.sound_button.setText("Unmute" if self.backdrop.muted else "Mute")

        if self._video_error:
            # Leave the message from the player in place.
            return
        if not MULTIMEDIA_AVAILABLE:
            self.video_note.setText(
                "Video playback needs PySide6-Addons  ·  pip install PySide6-Addons"
            )
        elif has_video:
            self.video_note.setText(Path(self._video_path).name)
        elif requested:
            self.video_note.setText("That file could not be played.")
        else:
            self.video_note.setText(
                "Plays on a loop behind this page. The file is used where it "
                "is, not copied."
            )

    def _choose_video(self) -> None:
        start = str(Path(self._video_path).parent) if self._video_path else ""
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choose a background video", start, FILE_FILTER
        )
        if chosen:
            self.set_video(chosen)

    def _clear_video(self) -> None:
        self.set_video("")

    def _toggle_play(self) -> None:
        self.backdrop.toggle_play()
        self._sync_controls()

    def _toggle_sound(self) -> None:
        self.backdrop.set_muted(not self.backdrop.muted)
        self._sync_controls()

    def _on_video_error(self, message: str) -> None:
        self.video_note.setText(message)
        self.video_note.setStyleSheet(f"color: {theme.WARN};")
        self._video_error = True

    # -- lifecycle -------------------------------------------------------

    def set_active(self, active: bool) -> None:
        """Pause decoding while the tab is not on screen."""
        if not self._video_path:
            return
        self.backdrop.play() if active else self.backdrop.pause()
        self._sync_controls()

    def release(self) -> None:
        self.backdrop.release()
