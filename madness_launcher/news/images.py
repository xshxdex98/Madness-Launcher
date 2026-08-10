"""Thumbnails for the news tab, fetched once and kept.

Video cards are worth very little without their thumbnails, but a tab that
fires twenty image requests every time it is opened is worth even less. Images
are therefore cached on disk under the launcher's own root and read from there
on subsequent runs, so the tab is fully drawn offline after one visit.

Only hosts on the model's allowlist are ever contacted — see IMAGE_HOSTS.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import paths
from .model import safe_image_url
from .service import USER_AGENT

# A YouTube mqdefault is about 15KB; the ceiling is for a host that decides to
# answer with something else entirely.
MAX_IMAGE_BYTES = 3_145_728

# Enough to fill the visible part of the list at once without opening twenty
# sockets to the same CDN.
MAX_IN_FLIGHT = 4

# Decoded pixmaps held in memory. Bounded because a long session scrolling a
# feed should not accumulate every thumbnail it has ever seen.
MEMORY_LIMIT = 64

TIMEOUT_MS = 15_000


def thumb_dir() -> Path:
    return paths.app_root() / "cache" / "thumbs"


def _key(url: str) -> str:
    """A filename for a URL. Hashed because a URL is not a valid path."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


class ThumbnailCache(QObject):
    """Hands out pixmaps for image URLs, fetching them at most once."""

    # url, pixmap — a card connects to this and matches on its own URL.
    ready = Signal(str, QPixmap)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._memory: OrderedDict[str, QPixmap] = OrderedDict()
        self._queue: deque[str] = deque()
        self._in_flight: dict[QNetworkReply, str] = {}
        # URLs that failed. Retrying them on every repaint would turn one dead
        # thumbnail into a steady trickle of requests.
        self._failed: set[str] = set()

        self._net = QNetworkAccessManager(self)
        self._net.setRedirectPolicy(QNetworkRequest.NoLessSafeRedirectPolicy)

    # -- lookup ----------------------------------------------------------

    def cached(self, url: str) -> QPixmap | None:
        """The pixmap for a URL if it is already available, without fetching."""
        url = safe_image_url(url)
        if not url:
            return None
        found = self._memory.get(url)
        if found is not None:
            self._memory.move_to_end(url)
            return found
        return self._read_disk(url)

    def local_path(self, url: str) -> str:
        """The on-disk file backing a cached image, or empty if not there yet.

        Rich text in a QLabel cannot fetch over the network, so an inline
        `<img>` — a custom emoji in the middle of a sentence — has to point at
        a file that already exists. Returned with forward slashes because the
        path goes into an HTML attribute, where a Windows backslash is an
        escape character rather than a separator.
        """
        url = safe_image_url(url)
        if not url:
            return ""
        path = self._path_for(url)
        return path.as_posix() if path.is_file() else ""

    def request(self, url: str) -> QPixmap | None:
        """The pixmap now, or None with `ready` to follow if it can be had."""
        url = safe_image_url(url)
        if not url or url in self._failed:
            return None
        found = self.cached(url)
        if found is not None:
            return found
        if url in self._queue or url in self._in_flight.values():
            return None
        self._queue.append(url)
        self._pump()
        return None

    # -- disk ------------------------------------------------------------

    def _path_for(self, url: str) -> Path:
        return thumb_dir() / _key(url)

    def _read_disk(self, url: str) -> QPixmap | None:
        path = self._path_for(url)
        if not path.is_file():
            return None
        pixmap = QPixmap()
        if not pixmap.load(str(path)):
            # Truncated by a previous crash mid-write; drop it and refetch.
            path.unlink(missing_ok=True)
            return None
        self._remember(url, pixmap)
        return pixmap

    def _remember(self, url: str, pixmap: QPixmap) -> None:
        self._memory[url] = pixmap
        self._memory.move_to_end(url)
        while len(self._memory) > MEMORY_LIMIT:
            self._memory.popitem(last=False)

    # -- fetching --------------------------------------------------------

    def _pump(self) -> None:
        while self._queue and len(self._in_flight) < MAX_IN_FLIGHT:
            url = self._queue.popleft()
            request = QNetworkRequest(QUrl(url))
            request.setRawHeader(b"User-Agent", USER_AGENT)
            request.setTransferTimeout(TIMEOUT_MS)
            reply = self._net.get(request)
            self._in_flight[reply] = url
            reply.downloadProgress.connect(
                lambda received, total, r=reply: self._on_progress(r, received, total)
            )
            reply.finished.connect(lambda r=reply: self._on_finished(r))

    def _on_progress(self, reply: QNetworkReply, received: int, total: int) -> None:
        if received > MAX_IMAGE_BYTES or total > MAX_IMAGE_BYTES:
            reply.abort()

    def _on_finished(self, reply: QNetworkReply) -> None:
        url = self._in_flight.pop(reply, "")
        reply.deleteLater()
        if not url:
            return

        payload = bytes(reply.readAll()) if reply.error() == QNetworkReply.NoError else b""
        if not payload or len(payload) > MAX_IMAGE_BYTES:
            self._failed.add(url)
            self._pump()
            return

        pixmap = QPixmap()
        # Decoded before it is written, so a cache file is only ever created
        # for bytes Qt could actually read as an image.
        if not pixmap.loadFromData(payload):
            self._failed.add(url)
            self._pump()
            return

        self._remember(url, pixmap)
        try:
            paths.ensure_dirs(thumb_dir())
            self._path_for(url).write_bytes(payload)
        except OSError:
            # In memory is enough for this session.
            pass

        self.ready.emit(url, pixmap)
        self._pump()

    def stop(self) -> None:
        """Abandon everything outstanding, on shutdown."""
        self._queue.clear()
        for reply in list(self._in_flight):
            reply.abort()
            reply.deleteLater()
        self._in_flight.clear()
