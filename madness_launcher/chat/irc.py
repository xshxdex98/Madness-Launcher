"""A minimal IRC client for the chat room.

Built on QSslSocket rather than a thread and a blocking socket, so everything
arrives on the GUI thread and the UI never has to marshal across threads.

Only the parts a chat room needs are implemented: registration, one channel,
messages, and the membership bookkeeping that keeps the user list honest
(JOIN/PART/QUIT/KICK/NICK). Outgoing traffic is paced, because IRC networks
disconnect clients that send faster than a person could type.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QSslSocket

from .. import __version__

DEFAULT_HOST = "irc.libera.chat"
DEFAULT_TLS_PORT = 6697
DEFAULT_PLAIN_PORT = 6667
DEFAULT_CHANNEL = "#madness-launcher"

# IRC lines cap at 512 bytes including the prefix the server prepends and the
# trailing CRLF. This leaves comfortable room for both.
MAX_MESSAGE_BYTES = 400
# Networks kill clients that flood. One line per 1.2s is well inside the limit.
SEND_INTERVAL_MS = 1200


@dataclass
class IrcConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_TLS_PORT
    channel: str = DEFAULT_CHANNEL
    use_tls: bool = True


def parse_line(line: str) -> tuple[str, str, list[str]]:
    """Split an IRC line into (prefix, command, params).

    The final parameter may be introduced by a colon and contain spaces.
    """
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")

    trailing = ""
    has_trailing = False
    if " :" in line:
        line, _, trailing = line.partition(" :")
        has_trailing = True
    elif line.startswith(":"):
        trailing, line, has_trailing = line[1:], "", True

    params = line.split()
    if has_trailing:
        params.append(trailing)
    command = params.pop(0).upper() if params else ""
    return prefix, command, params


def nick_of(prefix: str) -> str:
    """The nickname portion of a `nick!user@host` prefix."""
    return prefix.split("!", 1)[0]


class IrcClient(QObject):
    """One connection to one channel."""

    connected_changed = Signal(bool)
    status = Signal(str)               # human-readable connection state
    message = Signal(str, str)         # nick, text
    system_message = Signal(str)       # joins, parts, notices
    users_changed = Signal(list)       # sorted nicknames currently in channel
    nick_rejected = Signal(str, str)   # attempted nick, reason
    failed = Signal(str)               # fatal-ish error text

    def __init__(self, config: IrcConfig | None = None, parent=None):
        super().__init__(parent)
        self.config = config or IrcConfig()
        self._socket: QSslSocket | None = None
        self._buffer = b""
        self._nick = ""
        self._registered = False
        self._users: set[str] = set()
        # Names arrive across several 353 replies, so collect then commit on 366.
        self._pending_names: set[str] = set()
        self._outbox: list[str] = []
        self._deliberate_quit = False

        self._pump = QTimer(self)
        self._pump.setInterval(SEND_INTERVAL_MS)
        self._pump.timeout.connect(self._drain_outbox)

    # -- state -----------------------------------------------------------

    @property
    def nick(self) -> str:
        return self._nick

    @property
    def users(self) -> list[str]:
        return sorted(self._users, key=str.lower)

    @property
    def online(self) -> bool:
        return self._registered

    # -- lifecycle -------------------------------------------------------

    def connect_as(self, nick: str) -> None:
        self.disconnect_from_server()
        self._nick = nick
        self._registered = False
        self._deliberate_quit = False
        self._buffer = b""
        self._users.clear()
        self._pending_names.clear()
        self.users_changed.emit([])

        socket = QSslSocket(self)
        socket.readyRead.connect(self._on_ready_read)
        socket.disconnected.connect(self._on_disconnected)
        socket.errorOccurred.connect(self._on_socket_error)
        socket.sslErrors.connect(self._on_ssl_errors)
        self._socket = socket

        target = f"{self.config.host}:{self.config.port}"
        self.status.emit(f"Connecting to {target}…")
        if self.config.use_tls:
            socket.connectToHostEncrypted(self.config.host, self.config.port)
            socket.encrypted.connect(self._register)
        else:
            socket.connected.connect(self._register)
            socket.connectToHost(self.config.host, self.config.port)

    def disconnect_from_server(self, reason: str = "Leaving") -> None:
        self._pump.stop()
        self._outbox.clear()
        if self._socket is not None:
            self._deliberate_quit = True
            if self._socket.state() == QAbstractSocket.ConnectedState:
                self._raw(f"QUIT :{reason}")
                self._socket.flush()
                self._socket.disconnectFromHost()
            self._socket.abort()
            self._socket.deleteLater()
            self._socket = None
        if self._registered:
            self._registered = False
            self.connected_changed.emit(False)
        self._users.clear()
        self.users_changed.emit([])

    def _register(self) -> None:
        self.status.emit("Registering…")
        self._raw(f"NICK {self._nick}")
        self._raw(f"USER {self._nick} 0 * :Madness Launcher user")
        self._pump.start()

    # -- sending ---------------------------------------------------------

    def _raw(self, line: str) -> None:
        """Write a line immediately, bypassing the pacing queue."""
        if self._socket is None:
            return
        self._socket.write((line + "\r\n").encode("utf-8", "replace"))

    def _queue(self, line: str) -> None:
        self._outbox.append(line)

    def _drain_outbox(self) -> None:
        if self._outbox and self._socket is not None:
            self._raw(self._outbox.pop(0))

    def send_message(self, text: str) -> bool:
        """Say something in the channel. Returns False if not connected."""
        text = text.strip()
        if not text or not self._registered:
            return False
        for chunk in self._split(text):
            self._queue(f"PRIVMSG {self.config.channel} :{chunk}")
        return True

    @staticmethod
    def _split(text: str) -> list[str]:
        """Break an over-long message on byte length, not character count.

        Prefers word boundaries, but a single word longer than the limit — a
        pasted URL, say — still has to be cut, or it would never be sent.
        """
        if len(text.encode("utf-8")) <= MAX_MESSAGE_BYTES:
            return [text]

        def hard_cut(word: str) -> list[str]:
            pieces, current, size = [], [], 0
            for char in word:
                width = len(char.encode("utf-8"))
                if size + width > MAX_MESSAGE_BYTES:
                    pieces.append("".join(current))
                    current, size = [], 0
                current.append(char)
                size += width
            if current:
                pieces.append("".join(current))
            return pieces

        chunks, current = [], ""
        for word in text.split(" "):
            oversized = len(word.encode("utf-8")) > MAX_MESSAGE_BYTES
            for piece in (hard_cut(word) if oversized else [word]):
                candidate = f"{current} {piece}".strip()
                if current and len(candidate.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    chunks.append(current)
                    current = piece
                else:
                    current = candidate
        if current:
            chunks.append(current)
        return chunks

    def change_nick(self, nick: str) -> None:
        self._nick = nick
        if self._socket is not None:
            self._raw(f"NICK {nick}")

    # -- receiving -------------------------------------------------------

    def _on_ready_read(self) -> None:
        if self._socket is None:
            return
        self._buffer += bytes(self._socket.readAll())
        while b"\r\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\r\n", 1)
            if raw:
                self._handle(raw.decode("utf-8", "replace"))

    def _handle(self, line: str) -> None:
        prefix, command, params = parse_line(line)

        if command == "PING":
            self._raw(f"PONG :{params[-1] if params else ''}")
            return

        handler = getattr(self, f"_on_{command.lower()}", None)
        if handler is not None:
            handler(prefix, params)
        elif command in ("001",):
            self._on_welcome()
        elif command == "353":
            self._on_names(params)
        elif command == "366":
            self._on_names_end()
        elif command in ("433", "432", "436"):
            self._on_nick_unavailable(command, params)
        elif command in ("473", "474", "475", "471", "477"):
            self.failed.emit(
                params[-1] if params else "The channel refused the connection."
            )

    def _on_welcome(self) -> None:
        self.status.emit(f"Joining {self.config.channel}…")
        self._raw(f"JOIN {self.config.channel}")

    def _on_names(self, params: list[str]) -> None:
        if not params:
            return
        for entry in params[-1].split():
            # Strip channel-status prefixes such as @ (op) and + (voice).
            self._pending_names.add(entry.lstrip("~&@%+"))

    def _on_names_end(self) -> None:
        self._users = set(self._pending_names)
        self._pending_names.clear()
        if not self._registered:
            self._registered = True
            self.connected_changed.emit(True)
            self.status.emit(f"Connected to {self.config.channel}")
        self.users_changed.emit(self.users)

    def _on_nick_unavailable(self, code: str, params: list[str]) -> None:
        attempted = params[1] if len(params) > 1 else self._nick
        reasons = {
            "433": "That username is already in use by someone online.",
            "432": "The network rejected that username.",
            "436": "That username collided with another user.",
        }
        self.nick_rejected.emit(attempted, reasons.get(code, "Username refused."))
        self.disconnect_from_server()

    # -- membership ------------------------------------------------------

    def _on_join(self, prefix: str, params: list[str]) -> None:
        who = nick_of(prefix)
        if who and who != self._nick:
            self._users.add(who)
            self.users_changed.emit(self.users)
            self.system_message.emit(f"{who} joined")

    def _on_part(self, prefix: str, params: list[str]) -> None:
        self._remove(nick_of(prefix), "left")

    def _on_quit(self, prefix: str, params: list[str]) -> None:
        self._remove(nick_of(prefix), "disconnected")

    def _on_kick(self, prefix: str, params: list[str]) -> None:
        if len(params) >= 2:
            self._remove(params[1], "was removed")

    def _remove(self, who: str, verb: str) -> None:
        if who and who in self._users:
            self._users.discard(who)
            self.users_changed.emit(self.users)
            self.system_message.emit(f"{who} {verb}")

    def _on_nick(self, prefix: str, params: list[str]) -> None:
        old, new = nick_of(prefix), params[-1] if params else ""
        if not new:
            return
        if old == self._nick:
            self._nick = new
        self._users.discard(old)
        self._users.add(new)
        self.users_changed.emit(self.users)
        self.system_message.emit(f"{old} is now {new}")

    # -- messages --------------------------------------------------------

    def _on_privmsg(self, prefix: str, params: list[str]) -> None:
        if len(params) < 2:
            return
        who, text = nick_of(prefix), params[-1]

        # CTCP: answer VERSION, render /me, ignore the rest.
        if text.startswith("\x01") and text.endswith("\x01"):
            inner = text.strip("\x01")
            verb, _, rest = inner.partition(" ")
            if verb.upper() == "VERSION":
                self._queue(
                    f"NOTICE {who} :\x01VERSION Madness Launcher {__version__}\x01"
                )
            elif verb.upper() == "ACTION":
                self.system_message.emit(f"* {who} {rest}")
            return

        self.message.emit(who, text)

    def _on_notice(self, prefix: str, params: list[str]) -> None:
        if params and not self._registered:
            # Pre-registration notices are the server explaining itself.
            self.status.emit(params[-1][:120])

    def _on_error(self, prefix: str, params: list[str]) -> None:
        if not self._deliberate_quit:
            self.failed.emit(params[-1] if params else "The server closed the link.")

    # -- socket problems -------------------------------------------------

    def _on_ssl_errors(self, errors) -> None:
        self.failed.emit(
            "The server's certificate could not be verified: "
            + "; ".join(e.errorString() for e in errors)
        )

    def _on_socket_error(self, _error) -> None:
        if self._socket is not None and not self._deliberate_quit:
            self.failed.emit(self._socket.errorString())

    def _on_disconnected(self) -> None:
        was_online = self._registered
        self._registered = False
        self._pump.stop()
        self._users.clear()
        self.users_changed.emit([])
        if was_online:
            self.connected_changed.emit(False)
        if not self._deliberate_quit:
            self.status.emit("Disconnected")
