"""Choosing a username, on first run and whenever it is changed afterwards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .. import APP_NAME, identity
from . import theme


class UsernameDialog(QDialog):
    """Validates as you type, so the OK button never lies about what it does."""

    def __init__(self, current: str = "", first_run: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            f"Welcome to {APP_NAME}" if first_run else "Change username"
        )
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 20)
        layout.setSpacing(14)

        heading = QLabel(
            "Choose a username" if first_run else "Change your username"
        )
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        blurb = QLabel(
            "This is the name other people see in the chat room."
            + (
                "  You can change it later in Settings."
                if first_run
                else "  If you are connected to chat, you will be renamed there too."
            )
        )
        blurb.setObjectName("Faint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self.field = QLineEdit(current)
        self.field.setMaxLength(identity.MAX_LENGTH)
        self.field.setPlaceholderText("RoadHog99")
        self.field.textChanged.connect(self._validate)
        layout.addWidget(self.field)

        self.hint = QLabel(identity.RULES)
        self.hint.setObjectName("Faint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        self.buttons.button(QDialogButtonBox.Ok).setText(
            "Continue" if first_run else "Save"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if first_run:
            # There is no sensible "cancel" out of first run; the launcher needs
            # a name before it can offer chat at all.
            self.buttons.button(QDialogButtonBox.Cancel).setText("Skip for now")

        self._validate(self.field.text())
        self.field.setFocus()

    def _validate(self, text: str) -> None:
        error = identity.validate(text)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(error is None)
        if not text:
            self.hint.setText(identity.RULES)
            self.hint.setStyleSheet(f"color: {theme.FAINT};")
        elif error:
            self.hint.setText(error)
            self.hint.setStyleSheet(f"color: {theme.WARN};")
        else:
            self.hint.setText("Looks good.")
            self.hint.setStyleSheet(f"color: {theme.GOOD};")

    def username(self) -> str:
        return self.field.text().strip()
