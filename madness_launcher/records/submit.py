"""Sending a lap record to the community board.

A Discord webhook is the right shape for this and the wrong shape for very
little: it can only write. Whatever the launcher holds, it cannot use it to
read the server, list channels, or act as the bot — which is exactly the
property the news relay was built to preserve, in the opposite direction.

What it cannot do is prove who sent something. The URL ships inside the
executable and can be extracted, so anybody can POST to it directly and
invent whatever they like. That is not fixable client-side: signing needs a
key, and the key would ship too. What makes it workable is that every
submission lands as a message in a channel you moderate, so a bad entry is
visible and deletable rather than silently authoritative.

The URL is not compiled in. It arrives in the news feed the launcher already
fetches, so rotating it after abuse is a change to one JSON file rather than
a new build that every user has to download.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..news.model import safe_url
from ..news.service import USER_AGENT
from .session import Submission

TIMEOUT_MS = 15_000

# Discord's own limit is 2000 characters; a record is nowhere near it, but a
# malformed one should fail here rather than at their end.
MAX_CONTENT = 1800

# Only Discord's webhook endpoint. A "webhook" pointing anywhere else is a way
# to make every launcher post its user's name and play data to a third party,
# and the URL arrives over the network in the same feed as everything else.
_ALLOWED_HOSTS = ("discord.com", "discordapp.com", "ptb.discord.com")


def usable_webhook(url: str) -> str:
    """The webhook URL if it is one we are willing to POST to, else empty."""
    checked = safe_url(url)
    if not checked:
        return ""
    from urllib.parse import urlsplit

    parts = urlsplit(checked)
    if parts.scheme != "https":
        return ""
    host = (parts.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        return ""
    if "/api/webhooks/" not in parts.path:
        return ""
    return checked


def describe(entry: Submission) -> str:
    """The message text. Readable in Discord, and parseable by the relay.

    Written as one line of `key=value` pairs rather than prose so that the
    relay reads it back without guessing, and a human scrolling the channel
    can still see at a glance what was claimed.
    """
    fields = {
        "game": entry.game,
        "board": entry.board,
        "race": entry.race,
        "name": entry.race_name,
        "kind": entry.race_kind,
        "diff": entry.difficulty,
        "car": entry.car,
        "time": f"{entry.seconds:.3f}",
        "by": entry.username or entry.driver,
        "at": entry.set_at,
    }
    encoded = " ".join(f"{k}={json.dumps(str(v))}" for k, v in fields.items())
    headline = (
        f"**{entry.formatted}** — {entry.race_name} "
        f"({entry.race_kind}, {entry.difficulty}) in a {entry.car_name}, "
        f"by {entry.username or entry.driver} [{entry.board}]"
    )
    return f"{headline}\n`{encoded}`"[:MAX_CONTENT]


class RecordSubmitter(QObject):
    """POSTs records to the webhook, one at a time."""

    sent = Signal(object)
    failed = Signal(object, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        self._net.setRedirectPolicy(QNetworkRequest.NoLessSafeRedirectPolicy)
        self._queue: list[tuple[str, Submission]] = []
        self._busy = False

    def submit(self, webhook: str, entries: list[Submission]) -> int:
        """Queue records for sending. Returns how many were accepted."""
        target = usable_webhook(webhook)
        if not target:
            return 0
        for entry in entries:
            self._queue.append((target, entry))
        self._pump()
        return len(entries)

    def _pump(self) -> None:
        if self._busy or not self._queue:
            return
        target, entry = self._queue.pop(0)
        self._busy = True

        request = QNetworkRequest(QUrl(target))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        request.setTransferTimeout(TIMEOUT_MS)
        payload = json.dumps(
            {
                "content": describe(entry),
                # The webhook must never be able to ping the whole server,
                # whatever ends up in a race or car name.
                "allowed_mentions": {"parse": []},
            }
        ).encode("utf-8")

        reply = self._net.post(request, payload)
        reply.finished.connect(lambda r=reply, e=entry: self._done(r, e))

    def _done(self, reply: QNetworkReply, entry: Submission) -> None:
        reply.deleteLater()
        self._busy = False
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if reply.error() != QNetworkReply.NoError:
            self.failed.emit(entry, reply.errorString())
        elif isinstance(status, int) and status >= 400:
            self.failed.emit(entry, f"the board answered {status}")
        else:
            self.sent.emit(entry)
        self._pump()
