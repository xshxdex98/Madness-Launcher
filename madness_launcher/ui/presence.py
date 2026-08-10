"""Who else has the launcher open.

The count is the membership of the chat room the launcher already uses, so it
needs a connection that outlives the Chat Room page — a count that only appears
once you open chat is not a live count.

That connection is shared with the chat page rather than being a second one.
Two sockets from one machine would count the user twice and put twice the load
on a volunteer-run network for no gain.

Presence is announced, not observed: being counted means being in the room, and
the room is public. The setting behind it is therefore explicit and reversible,
and nothing connects until the user has a name to connect under.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from .. import identity
from ..chat import DEFAULT_CHANNEL, DEFAULT_HOST, DEFAULT_TLS_PORT, IrcClient, IrcConfig
from ..config import Config

# Reconnect backoff. A launcher can sit open for days, so it has to survive a
# dropped link, but must not hammer the network on a persistent outage.
RETRY_DELAYS_MS = (5_000, 15_000, 45_000, 120_000, 300_000)

# How many times to try a suffixed nickname when the chosen one is taken.
MAX_NICK_ATTEMPTS = 4


class Presence(QObject):
    """Keeps the shared IRC connection alive and reports the head count."""

    count_changed = Signal(int)
    state_changed = Signal(str)  # "online" | "connecting" | "offline" | "disabled"

    def __init__(self, config: Config, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self._count = 0
        self._state = "offline"
        self._attempt = 0
        self._retry_index = 0
        self._user_holds_connection = False

        self.client = IrcClient(self._irc_config(), parent=self)
        self.client.users_changed.connect(self._on_users_changed)
        self.client.connected_changed.connect(self._on_connected_changed)
        self.client.nick_rejected.connect(self._on_nick_rejected)
        self.client.failed.connect(self._on_failed)

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._reconnect)

    # -- state -----------------------------------------------------------

    @property
    def count(self) -> int:
        return self._count

    @property
    def state(self) -> str:
        return self._state

    @property
    def enabled(self) -> bool:
        return bool(self.config.settings.show_online_count)

    def _irc_config(self) -> IrcConfig:
        settings = self.config.settings
        return IrcConfig(
            host=settings.chat_host or DEFAULT_HOST,
            port=settings.chat_port or DEFAULT_TLS_PORT,
            channel=settings.chat_channel or DEFAULT_CHANNEL,
            use_tls=settings.chat_tls,
        )

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _set_count(self, count: int) -> None:
        if count != self._count:
            self._count = count
            self.count_changed.emit(count)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Join the room, if the user has agreed to be counted and has a name."""
        self._retry.stop()
        if not self.enabled:
            self._set_count(0)
            self._set_state("disabled")
            return
        name = self.config.settings.username
        if not identity.is_valid(name):
            # No name yet: first run has not finished. Nothing to announce.
            self._set_count(0)
            self._set_state("offline")
            return
        if self.client.online:
            return
        self._attempt = 0
        self._retry_index = 0
        self._connect_now(name)

    def _connect_now(self, nick: str) -> None:
        self._set_state("connecting")
        self.client.config = self._irc_config()
        self.client.connect_as(nick)

    def stop(self, reason: str = "Closing the launcher") -> None:
        self._retry.stop()
        self.client.disconnect_from_server(reason)
        self._set_count(0)
        self._set_state("disabled" if not self.enabled else "offline")

    def refresh(self) -> None:
        """React to the setting or the username changing."""
        if not self.enabled:
            self.stop("Leaving")
            self._set_state("disabled")
            return
        if self.client.online:
            return
        self.start()

    def note_user_connected(self) -> None:
        """The chat page took the connection over; presence must not fight it."""
        self._user_holds_connection = True
        self._retry.stop()

    def note_user_disconnected(self) -> None:
        """The user left chat deliberately. Stay out until they say otherwise."""
        self._user_holds_connection = False
        self._retry.stop()
        self._set_count(0)
        self._set_state("offline")

    # -- signals ---------------------------------------------------------

    def _on_users_changed(self, users: list) -> None:
        self._set_count(len(users))

    def _on_connected_changed(self, connected: bool) -> None:
        if connected:
            self._retry_index = 0
            self._set_state("online")
            return
        self._set_count(0)
        self._set_state("offline")
        # A drop we did not ask for: come back on our own.
        if self.enabled and not self._user_holds_connection:
            self._schedule_retry()

    def _on_nick_rejected(self, attempted: str, reason: str) -> None:
        if self._user_holds_connection:
            # The chat page owns this: it will ask the user for another name.
            return
        # Checked before incrementing, so the counter settles at the cap
        # instead of climbing for as long as the server keeps refusing.
        if self._attempt >= MAX_NICK_ATTEMPTS:
            self._set_state("offline")
            return
        self._attempt += 1
        base = self.config.settings.username or attempted
        candidate = f"{base[:12]}{self._attempt + 1}"
        QTimer.singleShot(1500, lambda: self._connect_now(candidate))

    def _on_failed(self, message: str) -> None:
        self._set_count(0)
        self._set_state("offline")
        if self.enabled and not self._user_holds_connection:
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        if self._retry.isActive():
            return
        delay = RETRY_DELAYS_MS[min(self._retry_index, len(RETRY_DELAYS_MS) - 1)]
        self._retry_index += 1
        self._retry.start(delay)

    def _reconnect(self) -> None:
        if not self.enabled or self._user_holds_connection:
            return
        name = self.config.settings.username
        if identity.is_valid(name):
            self._connect_now(name)
