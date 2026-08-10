"""The News tab: announcements from Discord and the latest video uploads.

Read-only by design. Everything on this page came from the network, so nothing
here renders remote markup — text is escaped, then a deliberately small subset
of Discord's formatting is put back, and links are opened in the user's own
browser rather than inside the launcher.
"""

from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..news import Announcement, NewsFeed, NewsService, ThumbnailCache, Video, age_of
from ..news.model import safe_url
from . import theme
from .widgets import StatusDot, scrollable

THUMB_WIDTH = 168
THUMB_HEIGHT = 94
AVATAR_SIZE = 28
# Wide enough for a paragraph, narrow enough that a line of body text does not
# run the full width of a maximised window and become hard to track back.
CONTENT_MAX_WIDTH = 760


def open_link(url: str) -> None:
    """Hand a feed URL to the browser, if it is one we are willing to open."""
    target = safe_url(url)
    if target:
        QDesktopServices.openUrl(QUrl(target))


# Matched after escaping, so the text being scanned is already HTML-safe.
_URL_RE = re.compile(r"(https?://[^\s<>\"']+)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\*)", re.DOTALL)
_CODE_RE = re.compile(r"`([^`\n]+)`")
# Trailing punctuation is almost never part of the link someone pasted.
_TRAILING = ".,;:!?)]}'\""


def to_rich_text(text: str) -> str:
    """Escaped body text with links and a little Discord formatting restored.

    Only the three markers that actually turn up in announcement posts are
    handled. Everything else stays literal, which is the safe direction to be
    wrong in: an unrendered asterisk is a blemish, an unescaped tag is a hole.
    """
    escaped = html.escape(text)

    def link(match: re.Match[str]) -> str:
        url = match.group(1)
        tail = ""
        while url and url[-1] in _TRAILING:
            tail = url[-1] + tail
            url = url[:-1]
        if not url:
            return match.group(0)
        # html.escape turned & into &amp;, which is what an href should carry;
        # Qt decodes it again when the link is activated.
        return f'<a href="{url}" style="color: {theme.DEFAULT_ACCENT};">{url}</a>{tail}'

    body = _URL_RE.sub(link, escaped)
    body = _CODE_RE.sub(
        lambda m: f'<span style="font-family: Consolas, monospace; '
        f'color: {theme.TEXT};">{m.group(1)}</span>',
        body,
    )
    body = _BOLD_RE.sub(lambda m: f"<b>{m.group(1)}</b>", body)
    body = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1)}</i>", body)
    return body.replace("\n", "<br>")


def rounded(pixmap: QPixmap, width: int, height: int, radius: int = 6) -> QPixmap:
    """Cover-crop a pixmap to a fixed box with rounded corners.

    Thumbnails arrive at whatever aspect the source felt like — a YouTube
    mqdefault is 16:9 but a Discord attachment is anything at all — and cards
    of uneven height make the list look broken rather than varied.
    """
    ratio = pixmap.devicePixelRatio() or 1.0
    target = QPixmap(int(width * ratio), int(height * ratio))
    target.setDevicePixelRatio(ratio)
    target.fill(Qt.transparent)

    scaled = pixmap.scaled(
        target.size(),
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation,
    )

    painter = QPainter(target)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, width * ratio, height * ratio, radius * ratio,
                        radius * ratio)
    painter.setClipPath(clip)
    # Centred: the interesting part of a thumbnail is in the middle far more
    # often than it is in the top-left corner.
    x = (target.width() - scaled.width()) // 2
    y = (target.height() - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return target


def circular(pixmap: QPixmap, size: int) -> QPixmap:
    """An avatar, cropped to a circle."""
    ratio = pixmap.devicePixelRatio() or 1.0
    target = QPixmap(int(size * ratio), int(size * ratio))
    target.setDevicePixelRatio(ratio)
    target.fill(Qt.transparent)

    scaled = pixmap.scaled(
        target.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )
    painter = QPainter(target)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size * ratio, size * ratio)
    painter.setClipPath(clip)
    painter.drawPixmap(
        (target.width() - scaled.width()) // 2,
        (target.height() - scaled.height()) // 2,
        scaled,
    )
    painter.end()
    return target


class AnnouncementCard(QFrame):
    """One Discord post."""

    def __init__(self, item: Announcement, thumbs: ThumbnailCache):
        super().__init__()
        self.setObjectName("Card")
        self.item = item
        self._thumbs = thumbs
        # url -> (label, shape, box) for images still downloading.
        self._pending: dict[str, tuple[QLabel, str, tuple[int, int]]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 15, 18, 15)
        outer.setSpacing(11)

        outer.addLayout(self._build_head())

        body = QLabel(to_rich_text(item.body))
        body.setObjectName("NewsBody")
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setOpenExternalLinks(False)
        body.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        body.linkActivated.connect(open_link)
        body.setMaximumWidth(CONTENT_MAX_WIDTH)
        outer.addWidget(body)

        self.image_label: QLabel | None = None
        if item.image:
            self.image_label = QLabel()
            self.image_label.setFixedSize(320, 180)
            self.image_label.setObjectName("NewsImage")
            outer.addWidget(self.image_label, 0, Qt.AlignLeft)
            self._want(item.image, self.image_label, "rect", (320, 180))

        if item.url:
            row = QHBoxLayout()
            jump = QPushButton("Open in Discord")
            jump.setObjectName("LinkButton")
            jump.setCursor(Qt.PointingHandCursor)
            jump.clicked.connect(lambda: open_link(item.url))
            row.addWidget(jump)
            row.addStretch(1)
            outer.addLayout(row)

    def _build_head(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.avatar_label: QLabel | None = None
        if self.item.avatar:
            self.avatar_label = QLabel()
            self.avatar_label.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            row.addWidget(self.avatar_label, 0, Qt.AlignVCenter)
            self._want(
                self.item.avatar,
                self.avatar_label,
                "circle",
                (AVATAR_SIZE, AVATAR_SIZE),
            )

        author = QLabel(self.item.author)
        author.setObjectName("CardTitle")
        row.addWidget(author, 0, Qt.AlignVCenter)

        when = age_of(self.item.posted)
        if when:
            stamp = QLabel(when)
            stamp.setObjectName("Faint")
            if self.item.posted is not None:
                stamp.setToolTip(
                    self.item.posted.astimezone().strftime("%d %B %Y at %H:%M")
                )
            row.addWidget(stamp, 0, Qt.AlignVCenter)

        row.addStretch(1)
        return row

    # -- images ----------------------------------------------------------

    def _want(self, url: str, label: QLabel, shape: str, box: tuple[int, int]) -> None:
        """Show an image once it is available, now or later.

        The waiting connection is made to a bound method rather than a lambda
        so that Qt tears it down with this card. A lambda capturing `label`
        would outlive the widget and paint into a deleted object the next time
        any thumbnail finished downloading.
        """
        pixmap = self._thumbs.request(url)
        if pixmap is not None:
            label.setPixmap(self._shaped(pixmap, shape, box))
            return
        self._pending[url] = (label, shape, box)
        if len(self._pending) == 1:
            self._thumbs.ready.connect(self._on_image_ready)

    def _on_image_ready(self, url: str, pixmap: QPixmap) -> None:
        waiting = self._pending.pop(url, None)
        if waiting is None:
            return
        label, shape, box = waiting
        label.setPixmap(self._shaped(pixmap, shape, box))

    @staticmethod
    def _shaped(pixmap: QPixmap, shape: str, box: tuple[int, int]) -> QPixmap:
        if shape == "circle":
            return circular(pixmap, box[0])
        return rounded(pixmap, box[0], box[1])


class VideoCard(QFrame):
    """One upload. The whole card is the link."""

    def __init__(self, item: Video, thumbs: ThumbnailCache):
        super().__init__()
        self.setObjectName("GameCard")
        self.setCursor(Qt.PointingHandCursor)
        self.item = item
        self._thumbs = thumbs
        self.setToolTip(f"Watch “{item.title}” in your browser")

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 16, 12)
        row.setSpacing(14)

        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
        self.thumb.setObjectName("NewsThumb")
        self.thumb.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumb, 0, Qt.AlignVCenter)
        self._load_thumb()

        column = QVBoxLayout()
        column.setSpacing(5)

        title = QLabel(item.title)
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        title.setMaximumWidth(CONTENT_MAX_WIDTH - THUMB_WIDTH)
        column.addWidget(title)

        meta_bits = [bit for bit in (item.channel, age_of(item.published)) if bit]
        meta = QLabel(" · ".join(meta_bits))
        meta.setObjectName("Faint")
        column.addWidget(meta)

        if item.source == "discord":
            shared = QLabel("Shared in Discord")
            shared.setObjectName("Faint")
            shared.setToolTip(
                "Someone posted this link in the Discord, rather than it "
                "coming from a channel the launcher follows."
            )
            column.addWidget(shared)

        column.addStretch(1)
        row.addLayout(column, 1)

    def _load_thumb(self) -> None:
        if not self.item.thumbnail:
            self._placeholder()
            return
        pixmap = self._thumbs.request(self.item.thumbnail)
        if pixmap is not None:
            self.thumb.setPixmap(rounded(pixmap, THUMB_WIDTH, THUMB_HEIGHT))
            return
        self._placeholder()
        self._thumbs.ready.connect(self._on_thumb_ready)

    def _on_thumb_ready(self, url: str, pixmap: QPixmap) -> None:
        if url == self.item.thumbnail:
            self.thumb.setPixmap(rounded(pixmap, THUMB_WIDTH, THUMB_HEIGHT))

    def _placeholder(self) -> None:
        """A play triangle, so the card has its shape before the image lands."""
        ratio = self.devicePixelRatioF() or 1.0
        pixmap = QPixmap(int(THUMB_WIDTH * ratio), int(THUMB_HEIGHT * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ELEVATED))
        painter.drawRoundedRect(
            0, 0, THUMB_WIDTH * ratio, THUMB_HEIGHT * ratio, 6 * ratio, 6 * ratio
        )
        painter.setBrush(QColor(theme.BORDER_STRONG))
        centre_x = THUMB_WIDTH * ratio / 2
        centre_y = THUMB_HEIGHT * ratio / 2
        size = 13 * ratio
        triangle = QPainterPath()
        triangle.moveTo(centre_x - size * 0.5, centre_y - size)
        triangle.lineTo(centre_x + size, centre_y)
        triangle.lineTo(centre_x - size * 0.5, centre_y + size)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.end()
        self.thumb.setPixmap(pixmap)

    def mousePressEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            open_link(self.item.url)
        super().mousePressEvent(event)


class NewsPage(QWidget):
    """Announcements and videos, side by side in two tabs."""

    # Emitted when the page has read the feed, so the sidebar can drop its
    # unread marker.
    seen = Signal()

    def __init__(self, service: NewsService, thumbs: ThumbnailCache):
        super().__init__()
        self.service = service
        self.thumbs = thumbs

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 24)
        root.setSpacing(16)

        root.addWidget(self._build_header())
        root.addWidget(self._build_tabs(), 1)

        service.updated.connect(self._on_updated)
        service.state_changed.connect(self._refresh_status)
        self.rebuild()

    # -- construction ----------------------------------------------------

    def _build_header(self) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        column = QVBoxLayout()
        column.setSpacing(4)

        title = QLabel("News")
        title.setObjectName("PageTitle")
        column.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(7)
        self.status_dot = StatusDot("idle")
        row.addWidget(self.status_dot, 0, Qt.AlignVCenter)
        self.status_label = QLabel()
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, 1, Qt.AlignVCenter)
        column.addLayout(row)
        layout.addLayout(column, 1)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("Ghost")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(self.refresh_button, 0, Qt.AlignVCenter)

        return host

    def _build_tabs(self) -> QWidget:
        self.tabs = QTabWidget()

        self.announcement_column = QVBoxLayout()
        self.announcement_column.setSpacing(12)
        self.tabs.addTab(
            self._tab_body(self.announcement_column), "Announcements"
        )

        self.video_column = QVBoxLayout()
        self.video_column.setSpacing(10)
        self.tabs.addTab(self._tab_body(self.video_column), "Videos")

        return self.tabs

    @staticmethod
    def _tab_body(column: QVBoxLayout) -> QWidget:
        inner = QWidget()
        wrapper = QVBoxLayout(inner)
        wrapper.setContentsMargins(2, 14, 8, 14)
        wrapper.setSpacing(0)
        wrapper.addLayout(column)
        wrapper.addStretch(1)
        return scrollable(inner)

    # -- population ------------------------------------------------------

    def rebuild(self) -> None:
        """Redraw both lists from the service's current feed."""
        feed = self.service.feed
        self._fill_announcements(feed)
        self._fill_videos(feed)
        self._refresh_status()
        self._refresh_tab_labels(feed)

    def _fill_announcements(self, feed: NewsFeed) -> None:
        _clear(self.announcement_column)
        if not feed.announcements:
            self.announcement_column.addWidget(self._empty_notice(
                "No announcements yet."
                if self.service.url
                else "The launcher has not been told where to find the news."
            ))
            return
        for item in feed.announcements:
            self.announcement_column.addWidget(AnnouncementCard(item, self.thumbs))

    def _fill_videos(self, feed: NewsFeed) -> None:
        _clear(self.video_column)
        if not feed.videos:
            self.video_column.addWidget(self._empty_notice(
                "No videos yet."
                if self.service.url
                else "The launcher has not been told where to find the news."
            ))
            return
        for item in feed.videos:
            self.video_column.addWidget(VideoCard(item, self.thumbs))

    def _refresh_tab_labels(self, feed: NewsFeed) -> None:
        """Counts on the tabs, so the quiet one is obvious without a click."""
        self.tabs.setTabText(
            0,
            f"Announcements  {len(feed.announcements)}"
            if feed.announcements
            else "Announcements",
        )
        self.tabs.setTabText(
            1, f"Videos  {len(feed.videos)}" if feed.videos else "Videos"
        )

    @staticmethod
    def _empty_notice(text: str) -> QWidget:
        label = QLabel(text)
        label.setObjectName("Faint")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        label.setContentsMargins(0, 40, 0, 0)
        return label

    # -- status ----------------------------------------------------------

    def _refresh_status(self, _state: str = "") -> None:
        state = self.service.state
        self.refresh_button.setEnabled(state != "loading" and bool(self.service.url))

        if state == "unset" or not self.service.url:
            self.status_dot.set_state("idle")
            self.status_label.setText(
                "No news source is set. Add the feed URL under Settings → News."
            )
            return
        if state == "loading":
            self.status_dot.set_state("warn")
            self.status_label.setText("Checking for news…")
            return
        if state == "error":
            self.status_dot.set_state("bad")
            self.status_label.setText(
                self.service.error or "Could not reach the news source."
            )
            return
        if state == "stale":
            self.status_dot.set_state("warn")
            when = age_of(self.service.fetched_at)
            suffix = f" Showing news from {when}." if when else ""
            self.status_label.setText(
                (self.service.error or "Could not refresh.") + suffix
            )
            return
        if state == "ready":
            self.status_dot.set_state("good")
            when = age_of(self.service.fetched_at)
            self.status_label.setText(
                f"Up to date, checked {when}." if when else "Up to date."
            )
            return
        self.status_dot.set_state("idle")
        self.status_label.setText("Not checked yet.")

    # -- reactions -------------------------------------------------------

    def _on_refresh_clicked(self) -> None:
        self.service.refresh(force=True)

    def _on_updated(self, _feed: object) -> None:
        self.rebuild()
        # The user is looking at it, so whatever just arrived counts as read.
        if self.isVisible():
            self.service.mark_seen()
            self.seen.emit()

    def set_visible_to_user(self, visible: bool) -> None:
        """Called by the shell when this page becomes (or stops being) current."""
        if not visible:
            return
        self.service.mark_seen()
        self.seen.emit()
        self.service.refresh()
        self._refresh_status()


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
