"""Shown for a known game that has not been located on disk yet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from ..detect import identify_as
from ..games.base import GameDef
from . import theme
from .widgets import Card


class SetupPage(QWidget):
    """Ask the user where the game lives, then verify it."""

    located = Signal(str)  # game id

    def __init__(self, game: GameDef, config: Config):
        super().__init__()
        self.game = game
        self.config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 24)
        root.setSpacing(18)

        title = QLabel(self.game.title)
        title.setObjectName("PageTitle")
        root.addWidget(title)

        meta = QLabel(f"{game.year}  ·  {game.developer}")
        meta.setObjectName("PageSubtitle")
        root.addWidget(meta)

        card = Card(
            "Locate the game",
            "Point the launcher at your installation. Pick the folder that "
            "contains the game executable, or the executable itself.",
        )

        expect = QLabel(
            "The launcher looks for "
            + ", ".join(f"<b>{f}</b>" for f in game.signature_files)
            + (
                "<br>and expects these data files: "
                + ", ".join(f"<b>{f}</b>" for f in game.data_files)
                if game.data_files
                else ""
            )
        )
        expect.setObjectName("Faint")
        expect.setWordWrap(True)
        expect.setTextFormat(Qt.RichText)
        card.body.addWidget(expect)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)

        browse_folder = QPushButton("Select game folder…")
        browse_folder.setObjectName("Primary")
        browse_folder.clicked.connect(self._browse_folder)
        buttons.addWidget(browse_folder)

        browse_exe = QPushButton("Select executable…")
        browse_exe.setObjectName("Ghost")
        browse_exe.clicked.connect(self._browse_exe)
        buttons.addWidget(browse_exe)

        buttons.addStretch(1)
        card.body.addLayout(buttons)

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        card.body.addWidget(self.feedback)

        root.addWidget(card)
        root.addStretch(1)

    # ------------------------------------------------------------------

    def _browse_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, f"Select the {self.game.title} folder"
        )
        if chosen:
            self._accept(Path(chosen))

    def _browse_exe(self) -> None:
        names = " ".join(self.game.signature_files)
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            f"Select the {self.game.title} executable",
            "",
            f"Game executable ({names});;Executables (*.exe);;All files (*)",
        )
        if chosen:
            self._accept(Path(chosen))

    def _accept(self, selection: Path) -> None:
        result = identify_as(selection, self.game)
        if result is None:
            self.feedback.setStyleSheet(f"color: {theme.BAD};")
            self.feedback.setText(
                f"That location does not look like {self.game.title}. "
                f"Expected one of: {', '.join(self.game.signature_files)}."
            )
            self.feedback.show()
            return

        if not result.playable:
            self.feedback.setStyleSheet(f"color: {theme.BAD};")
            self.feedback.setText(
                "Found the folder, but no runnable executable inside it."
            )
            self.feedback.show()
            return

        if result.missing_data:
            proceed = QMessageBox.question(
                self,
                "Missing data files",
                f"{result.root}\n\nThese expected files are missing:\n"
                f"  {', '.join(result.missing_data)}\n\n"
                "The game may not start. Use this folder anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if proceed != QMessageBox.Yes:
                return

        install = self.config.install_or_new(self.game.id)
        install.path = str(result.root)
        install.target = result.found_targets[0].id
        try:
            self.config.save()
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return

        self.located.emit(self.game.id)
