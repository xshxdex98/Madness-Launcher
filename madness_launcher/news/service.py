"""Fetching the news feed, and remembering it between runs.

Built on QNetworkAccessManager rather than a thread and urllib, for the same
reason chat is built on QSslSocket: everything stays on the GUI thread and the
window never blocks on the network.

The launcher opens on the Library, so a news fetch is a background errand that
nobody is waiting for. It is therefore quiet about failure — the page falls
back to the last feed it managed to read from disk, which is far better than an
empty tab when someone opens the launcher on a train.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import APP_NAME, __version__, paths
from ..config import Config
from .model import NewsFeed, parse_time, safe_url

# A news file that has grown past this is a mistake at the relay, not something
# worth spending a user's connection on.
MAX_FEED_BYTES = 1_048_576

# The feed is regenerated on a cron measured in minutes, so hammering it on
# every visit to the tab buys nothing. The Refresh button bypasses this.
MIN_REFRESH_SECONDS = 300

# Long enough for a slow connection, short enough that the status line does not
# sit on "Checking…" for a whole session when the host is black-holing packets.
TIMEOUT_MS = 20_000

USER_AGENT = f"{APP_NAME.replace(' ', '')}/{__version__}".encode()


def cache_dir() -> Path:
    return paths.app_root() / "cache"


def feed_file() -> Path:
    return cache_dir() / "news.json"


def meta_file() -> Path:
    """Validators from the last successful fetch, kept beside the feed."""
    return cache_dir() / "news-meta.json"


class NewsService(QObject):
    """Owns the current feed: on disk, in memory, and in flight.

    One of these lives on the main window rather than on the page, so the
    sidebar can show an unread marker without the user ever having opened the
    News tab.
    """

    # The feed changed. Carries a NewsFeed; typed as object because Signal
    # cannot introspect a dataclass.
    updated = Signal(object)
    # "idle" | "loading" | "ready" | "stale" | "error" | "unset"
    state_changed = Signal(str)

    def __init__(self, config: Config, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self._feed = NewsFeed()
        self._state = "idle"
        self._error = ""
        self._reply: QNetworkReply | None = None
        self._last_attempt = 0.0
        self._fetched_at: datetime | None = None

        self._net = QNetworkAccessManager(self)
        # The relay may redirect (a raw.githubusercontent URL does), but never
        # from https down to http.
        self._net.setRedirectPolicy(QNetworkRequest.NoLessSafeRedirectPolicy)

        self._load_cache()

    # -- state -----------------------------------------------------------

    @property
    def feed(self) -> NewsFeed:
        return self._feed

    @property
    def state(self) -> str:
        return self._state

    @property
    def error(self) -> str:
        """Why the last fetch failed, for the page to show under the header."""
        return self._error

    @property
    def fetched_at(self) -> datetime | None:
        return self._fetched_at

    @property
    def url(self) -> str:
        """Where the feed is fetched from, or empty when nobody has said."""
        return safe_url(self.config.settings.news_url)

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    # -- disk ------------------------------------------------------------

    def _load_cache(self) -> None:
        """Read the last feed we saw, so the page has something immediately.

        Only if it came from the source currently configured. A cache is the
        previous answer from one particular URL; showing it after the URL has
        been changed would present one community's news as another's.
        """
        try:
            meta = json.loads(meta_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        if not self.url or meta.get("url") != self.url:
            return
        try:
            raw = json.loads(feed_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        feed = NewsFeed.from_dict(raw)
        if feed.is_empty:
            return
        self._feed = feed
        self._fetched_at = parse_time(meta.get("fetched_at"))
        self._set_state("stale")

    def _save_cache(self, payload: bytes, etag: str, modified: str) -> None:
        directory = cache_dir()
        try:
            paths.ensure_dirs(directory)
            _atomic_write(feed_file(), payload)
            meta = {
                "etag": etag,
                "last_modified": modified,
                "url": self.url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _atomic_write(
                meta_file(), json.dumps(meta, indent=2).encode("utf-8")
            )
        except OSError:
            # A cache that cannot be written is not worth interrupting anyone
            # over; the feed is already in memory and will be refetched.
            pass

    def _validators(self) -> tuple[str, str]:
        """The ETag and Last-Modified to revalidate with, if they still apply."""
        try:
            meta = json.loads(meta_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "", ""
        # Validators belong to one URL. Pointing the launcher at a different
        # feed and being told "304 Not Modified" would show the old server's
        # news forever.
        if meta.get("url") != self.url:
            return "", ""
        etag = meta.get("etag")
        modified = meta.get("last_modified")
        return (
            etag if isinstance(etag, str) else "",
            modified if isinstance(modified, str) else "",
        )

    # -- fetching --------------------------------------------------------

    def refresh(self, *, force: bool = False) -> None:
        """Fetch the feed, unless one is in flight or we just tried."""
        if self._reply is not None:
            return
        if not self.url:
            self._set_state("unset")
            return
        now = time.monotonic()
        if not force and self._last_attempt and now - self._last_attempt < MIN_REFRESH_SECONDS:
            return
        self._last_attempt = now

        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        request.setRawHeader(b"Accept", b"application/json")
        etag, modified = self._validators()
        if etag:
            request.setRawHeader(b"If-None-Match", etag.encode("ascii", "ignore"))
        if modified:
            request.setRawHeader(
                b"If-Modified-Since", modified.encode("ascii", "ignore")
            )
        request.setTransferTimeout(TIMEOUT_MS)
        # The feed is public data; sending cookies or credentials with it would
        # only be a way to leak them.
        request.setAttribute(QNetworkRequest.CookieLoadControlAttribute,
                             QNetworkRequest.Manual)
        request.setAttribute(QNetworkRequest.CookieSaveControlAttribute,
                             QNetworkRequest.Manual)

        self._error = ""
        self._set_state("loading")
        reply = self._net.get(request)
        self._reply = reply
        reply.downloadProgress.connect(self._on_progress)
        reply.finished.connect(self._on_finished)

    def _on_progress(self, received: int, total: int) -> None:
        """Stop a runaway download before it is in memory, not after."""
        if received > MAX_FEED_BYTES or total > MAX_FEED_BYTES:
            reply = self._reply
            if reply is not None:
                reply.abort()

    def _on_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        reply.deleteLater()

        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        error = reply.error()

        if error == QNetworkReply.OperationCanceledError:
            self._fail("The news file was too large, or the request timed out.")
            return
        if error != QNetworkReply.NoError:
            self._fail(reply.errorString())
            return
        if status == 304:
            # Nothing new. The cached feed we are already showing is current.
            self._fetched_at = datetime.now(timezone.utc)
            self._set_state("ready")
            return
        if isinstance(status, int) and status >= 400:
            self._fail(f"The news source answered {status}.")
            return

        payload = bytes(reply.readAll())
        if len(payload) > MAX_FEED_BYTES:
            self._fail("The news file was too large.")
            return
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._fail("The news source did not return readable JSON.")
            return

        feed = NewsFeed.from_dict(data)
        if feed.is_empty and not self._feed.is_empty:
            # An empty feed where we previously had one usually means the relay
            # published a broken file. Keep what we have and say so.
            self._fail("The news source returned nothing usable.")
            return

        self._feed = feed
        self._fetched_at = datetime.now(timezone.utc)
        self._error = ""
        self._save_cache(
            payload,
            _header(reply, b"ETag"),
            _header(reply, b"Last-Modified"),
        )
        self._set_state("ready")
        self.updated.emit(feed)

    def _fail(self, message: str) -> None:
        self._error = message
        # "error" only when there is nothing to show; with a cached feed on
        # screen the honest state is that it is old, not that it is broken.
        self._set_state("error" if self._feed.is_empty else "stale")

    def stop(self) -> None:
        """Drop any request in flight, on the way out of the application."""
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.abort()
            reply.deleteLater()

    # -- unread ----------------------------------------------------------

    def last_seen(self) -> datetime | None:
        return parse_time(self.config.settings.news_last_seen)

    def unread(self) -> int:
        return self._feed.unread_since(self.last_seen())

    def mark_seen(self) -> None:
        """Called when the page is opened; the badge clears from here."""
        newest = self._feed.newest
        if newest is None:
            return
        current = self.last_seen()
        if current is not None and current >= newest:
            return
        self.config.settings.news_last_seen = newest.isoformat()
        try:
            self.config.save()
        except OSError:
            # Worst case the badge comes back next launch.
            pass


def _header(reply: QNetworkReply, name: bytes) -> str:
    value = reply.rawHeader(name)
    return bytes(value).decode("ascii", "ignore") if value else ""


def _atomic_write(target: Path, payload: bytes) -> None:
    """Replace a cache file in one step, the way config.py writes settings."""
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, target)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise
