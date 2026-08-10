"""The chat room: transcript, input bar, and who is currently online."""

from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import identity
from ..chat import DEFAULT_CHANNEL, DEFAULT_HOST, DEFAULT_TLS_PORT, IrcClient, IrcConfig
from ..config import Config
from . import sound, theme
from .username_dialog import UsernameDialog
from .widgets import StatusDot

# Keeps a long session from growing without bound.
MAX_TRANSCRIPT_BLOCKS = 2000


class ChatPage(QWidget):
    """One IRC channel, presented as an old-fashioned chat room."""

    online_count_changed = Signal(int)
    username_changed = Signal(str)
    joined_chat = Signal()
    left_chat = Signal()

    def __init__(self, config: Config, client: IrcClient | None = None):
        super().__init__()
        self.config = config
        self._unread = 0
        self._is_visible = False
        # True once the user has pressed Join themselves. Until then the
        # connection belongs to presence, which retries quietly rather than
        # putting dialogs in front of someone who never opened this page.
        self._user_initiated = False

        # The connection is shared with the sidebar's online count when one is
        # supplied; a second socket would count this machine twice.
        self.client = client if client is not None else IrcClient(self._irc_config())
        self.shares_client = client is not None
        self.client.connected_changed.connect(self._on_connected_changed)
        self.client.status.connect(self._on_status)
        self.client.message.connect(self._on_message)
        self.client.system_message.connect(self._on_system_message)
        self.client.users_changed.connect(self._on_users_changed)
        self.client.nick_rejected.connect(self._on_nick_rejected)
        self.client.failed.connect(self._on_failed)

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 24)
        root.setSpacing(16)

        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_input())

        self._append_system(
            f"Not connected. This room is {self._irc_config().channel} on "
            f"{self._irc_config().host}, a public IRC network — anyone on it can "
            "read and join."
        )

    # -- configuration ---------------------------------------------------

    def _irc_config(self) -> IrcConfig:
        settings = self.config.settings
        return IrcConfig(
            host=settings.chat_host or DEFAULT_HOST,
            port=settings.chat_port or DEFAULT_TLS_PORT,
            channel=settings.chat_channel or DEFAULT_CHANNEL,
            use_tls=settings.chat_tls,
        )

    # -- construction ----------------------------------------------------

    def _build_header(self) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        column = QVBoxLayout()
        column.setSpacing(4)

        title = QLabel("Chat Room")
        title.setObjectName("PageTitle")
        column.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(7)
        self.status_dot = StatusDot("idle")
        row.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        self.status_label = QLabel("Not connected")
        self.status_label.setObjectName("Muted")
        row.addWidget(self.status_label, 0, Qt.AlignVCenter)
        row.addStretch(1)
        column.addLayout(row)
        layout.addLayout(column, 1)

        self.sound_button = QPushButton()
        self.sound_button.setObjectName("Ghost")
        self.sound_button.setCheckable(True)
        self.sound_button.setChecked(self.config.settings.chat_sound)
        self.sound_button.toggled.connect(self._on_sound_toggled)
        self._sync_sound_button()
        layout.addWidget(self.sound_button, 0, Qt.AlignVCenter)

        self.connect_button = QPushButton("Join chat")
        self.connect_button.setObjectName("Primary")
        self.connect_button.clicked.connect(self._toggle_connection)
        layout.addWidget(self.connect_button, 0, Qt.AlignVCenter)

        return host

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("ChatSplitter")
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("Transcript")
        self.transcript.setOpenExternalLinks(True)
        self.transcript.document().setMaximumBlockCount(MAX_TRANSCRIPT_BLOCKS)
        splitter.addWidget(self.transcript)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        self.users_heading = QLabel("ONLINE — 0")
        self.users_heading.setObjectName("GroupHeading")
        side_layout.addWidget(self.users_heading)

        self.users = QListWidget()
        self.users.setObjectName("UserList")
        self.users.setSelectionMode(QListWidget.NoSelection)
        self.users.setFocusPolicy(Qt.NoFocus)
        side_layout.addWidget(self.users, 1)
        splitter.addWidget(side)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([740, 210])
        return splitter

    def _build_input(self) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        self.input = QLineEdit()
        self.input.setObjectName("ChatInput")
        self.input.setPlaceholderText("Join the chat to say something…")
        self.input.setMaxLength(900)
        self.input.returnPressed.connect(self._send)
        self.input.setEnabled(False)
        layout.addWidget(self.input, 1)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._send)
        self.send_button.setEnabled(False)
        layout.addWidget(self.send_button)
        return host

    # -- transcript ------------------------------------------------------

    @staticmethod
    def _stamp() -> str:
        return datetime.now().strftime("%H:%M")

    def _append_html(self, markup: str) -> None:
        # Pin to the bottom only when already there, so reading back through
        # the log is not yanked away by an incoming message.
        bar = self.transcript.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4

        self.transcript.moveCursor(QTextCursor.End)
        self.transcript.insertHtml(markup + "<br>")
        if at_bottom:
            bar.setValue(bar.maximum())

    def _append_system(self, text: str) -> None:
        self._append_html(
            f'<span style="color:{theme.FAINT};">'
            f"[{self._stamp()}] {html.escape(text)}</span>"
        )

    def _append_message(self, nick: str, text: str, is_self: bool) -> None:
        name_colour = theme.GOOD if is_self else self._colour_for(nick)
        self._append_html(
            f'<span style="color:{theme.FAINT};">[{self._stamp()}]</span> '
            f'<span style="color:{name_colour};font-weight:600;">'
            f"{html.escape(nick)}</span>"
            f'<span style="color:{theme.FAINT};">:</span> '
            f'<span style="color:{theme.TEXT};">{html.escape(text)}</span>'
        )

    @staticmethod
    def _colour_for(nick: str) -> str:
        """A stable colour per nickname, so people are recognisable at a glance."""
        palette = (
            "#E0912F", "#5AA9E6", "#C58AF0", "#4CAF7D",
            "#E4736B", "#D9C04A", "#63C7C0", "#B48EE8",
        )
        return palette[sum(nick.lower().encode()) % len(palette)]

    # -- connection ------------------------------------------------------

    def _toggle_connection(self) -> None:
        if self.client.online or self.connect_button.text() == "Leave chat":
            self._user_initiated = False
            self.client.disconnect_from_server()
            self._append_system("You left the chat room.")
            self._reset_connection_ui()
            self.left_chat.emit()
            return

        name = self.config.settings.username
        if not identity.is_valid(name):
            name = self._ask_username()
            if not name:
                return

        self._user_initiated = True
        self.joined_chat.emit()
        if self.client.online:
            # Presence already has us in the room; just take the controls.
            self.connect_button.setText("Leave chat")
            self._on_connected_changed(True)
            return
        self.client.config = self._irc_config()
        self.connect_button.setText("Leave chat")
        self.client.connect_as(name)

    def _reset_connection_ui(self) -> None:
        self.connect_button.setText("Join chat")
        self.status_dot.set_state("idle")
        self.status_label.setText("Not connected")
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.input.setPlaceholderText("Join the chat to say something…")
        self.users.clear()
        self.users_heading.setText("ONLINE — 0")
        self.online_count_changed.emit(0)

    def _on_connected_changed(self, connected: bool) -> None:
        self.input.setEnabled(connected)
        self.send_button.setEnabled(connected)
        self.status_dot.set_state("good" if connected else "idle")
        if connected:
            self.connect_button.setText("Leave chat")
            self.input.setPlaceholderText(f"Message as {self.client.nick}…")
            self._append_system(f"You joined as {self.client.nick}.")
            self.input.setFocus()
        else:
            self._reset_connection_ui()

    def _on_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _on_users_changed(self, users: list) -> None:
        self.users.clear()
        for nick in users:
            item = QListWidgetItem(nick)
            if nick == self.client.nick:
                item.setText(f"{nick}  (you)")
            self.users.addItem(item)
        self.users_heading.setText(f"ONLINE — {len(users)}")
        self.online_count_changed.emit(len(users))

    def _on_message(self, nick: str, text: str) -> None:
        is_self = nick == self.client.nick
        self._append_message(nick, text, is_self)
        if not is_self:
            self._notify()

    def _on_system_message(self, text: str) -> None:
        self._append_system(text)

    def _on_nick_rejected(self, attempted: str, reason: str) -> None:
        if not self._user_initiated:
            # Presence is retrying under a different name on its own; a modal
            # here would interrupt someone who is not even looking at chat.
            return
        self._append_system(f"{reason} ({attempted})")
        self._reset_connection_ui()
        chosen = self._ask_username(
            f"{reason}\n\nPick a different username to join the chat."
        )
        if chosen:
            self.client.connect_as(chosen)
            self.connect_button.setText("Leave chat")

    def _on_failed(self, message: str) -> None:
        self._append_system(f"Connection problem: {message}")
        self._reset_connection_ui()

    # -- sending ---------------------------------------------------------

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        if not self.client.send_message(text):
            self._append_system("Not connected — nothing was sent.")
            return
        self._append_message(self.client.nick, text, is_self=True)
        self.input.clear()

    # -- username --------------------------------------------------------

    def _ask_username(self, prompt: str = "") -> str:
        dialog = UsernameDialog(self.config.settings.username, parent=self)
        if prompt:
            QMessageBox.information(self, "Username unavailable", prompt)
        if dialog.exec() != QDialog.Accepted:
            return ""
        name = dialog.username()
        self.config.settings.username = name
        try:
            self.config.save()
        except OSError:
            pass
        self.username_changed.emit(name)
        return name

    def apply_username(self, name: str) -> None:
        """Follow a rename made elsewhere in the UI."""
        if self.client.online and name and name != self.client.nick:
            self.client.change_nick(name)

    # -- notification ----------------------------------------------------

    def set_visible_to_user(self, visible: bool) -> None:
        self._is_visible = visible
        if visible:
            self._unread = 0

    def _notify(self) -> None:
        if not self.config.settings.chat_sound:
            return
        sound.play_notification()

    def _on_sound_toggled(self, on: bool) -> None:
        self.config.settings.chat_sound = on
        self._sync_sound_button()
        try:
            self.config.save()
        except OSError:
            pass

    def _sync_sound_button(self) -> None:
        on = self.sound_button.isChecked()
        self.sound_button.setText("Sound on" if on else "Sound off")
        self.sound_button.setToolTip(
            "A short tone plays when someone posts a message."
            if on
            else "New messages arrive silently."
        )

    # -- lifecycle -------------------------------------------------------

    def release(self) -> None:
        # When the connection is shared, presence owns its lifetime and closes
        # it on shutdown. Dropping it here would kill the sidebar's head count
        # every time this page is rebuilt.
        if not self.shares_client:
            self.client.disconnect_from_server()
