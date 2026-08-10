"""What a news feed contains, and how to read one without trusting it.

The feed arrives over the internet from a file the launcher does not control,
so every field is treated as hostile input: missing keys, wrong types, absurd
lengths and unusable URLs are normalised here rather than being allowed to
reach a widget. Parsing never raises — a feed that cannot be understood comes
back empty, and the page says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

# The relay writes this; a future incompatible shape bumps it and old launchers
# fall back to their cache rather than misreading the new format.
FEED_VERSION = 1

# Caps, applied on the way in. The page is a news tab, not an archive, and an
# oversized feed should degrade to "the newest N" rather than to a stalled UI.
MAX_ANNOUNCEMENTS = 30
MAX_VIDEOS = 24
MAX_BODY_CHARS = 2000
MAX_TITLE_CHARS = 200
MAX_NAME_CHARS = 80
# One post referencing more custom emoji than this is doing something other
# than talking, and each one costs a request and a cache entry.
MAX_EMOJIS = 32
# Discord's own rule for emoji names, which is what the `:name:` in a body
# will be matched against. Anchored, so nothing with punctuation or markup in
# it can become a substitution key.
EMOJI_NAME = re.compile(r"\w{1,32}")

# Where a thumbnail or avatar is allowed to come from. Anything else is dropped
# rather than fetched: the feed is only as trustworthy as whoever can write to
# it, and an <img src> pointing at an arbitrary host would turn a compromised
# news file into a way to make every launcher call out to that host.
IMAGE_HOSTS = frozenset(
    {
        "i.ytimg.com",
        "img.youtube.com",
        "cdn.discordapp.com",
        "media.discordapp.net",
    }
)


def safe_url(value: Any) -> str:
    """An http(s) URL, or empty when it is anything else.

    Guards the two places a feed URL is acted on: opening a link in the
    browser, and fetching an image. Without this a `file://` or `javascript:`
    entry in the feed would be handed straight to QDesktopServices.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) > 2048:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return text


def safe_image_url(value: Any) -> str:
    """A URL the launcher is willing to fetch an image from."""
    url = safe_url(value)
    if not url:
        return ""
    host = urlsplit(url).hostname or ""
    return url if host.lower() in IMAGE_HOSTS else ""


def _text(value: Any, limit: int) -> str:
    """A single trimmed string, truncated to `limit` characters."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) <= limit:
        return text
    # Cut on a word boundary when there is one nearby, so the ellipsis does not
    # land in the middle of a word.
    clipped = text[:limit]
    space = clipped.rfind(" ")
    if space > limit - 40:
        clipped = clipped[:space]
    return clipped.rstrip() + "…"


def emoji_map(value: Any) -> dict[str, str]:
    """`{name: image url}` for the custom emoji a post uses.

    The names become substitution keys against the post's own body, so they
    are held to Discord's own character rule rather than accepted as given —
    a "name" containing markup would otherwise be a way to inject it.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for name, url in list(value.items())[:MAX_EMOJIS]:
        if not isinstance(name, str) or not EMOJI_NAME.fullmatch(name):
            continue
        safe = safe_image_url(url)
        if safe:
            out[name] = safe
    return out


def parse_time(value: Any) -> datetime | None:
    """An ISO 8601 timestamp as an aware datetime, or None.

    Discord and YouTube both emit RFC 3339 with a trailing `Z`, which
    `fromisoformat` only learned to accept in 3.11; the substitution keeps this
    working on older interpreters.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A feed without an offset is read as UTC rather than as local time, which
    # is what both upstream sources actually mean.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_of(moment: datetime | None, *, now: datetime | None = None) -> str:
    """How long ago something happened, in the fewest words that stay honest.

    Anything older than a week is given as a date: "6 days ago" is useful,
    "43 days ago" is not, and the reader would rather see when it was.
    """
    if moment is None:
        return ""
    reference = now or datetime.now(timezone.utc)
    seconds = (reference - moment).total_seconds()
    if seconds < 0:
        # Clock skew between the relay and this machine, or a scheduled post.
        return "just now"
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        count = int(minutes)
        return f"{count} minute{'s' if count != 1 else ''} ago"
    hours = minutes / 60
    if hours < 24:
        count = int(hours)
        return f"{count} hour{'s' if count != 1 else ''} ago"
    days = hours / 24
    if days < 7:
        count = int(days)
        return f"{count} day{'s' if count != 1 else ''} ago"
    return moment.astimezone().strftime("%d %b %Y").lstrip("0")


@dataclass
class Announcement:
    """One post from the Discord announcements channel."""

    id: str = ""
    author: str = ""
    avatar: str = ""
    posted: datetime | None = None
    body: str = ""
    # A discord:// or https://discord.com/channels/... jump link, when the
    # relay was able to build one.
    url: str = ""
    image: str = ""
    # Custom emoji used in `body`, as `{name: url}`. The body keeps them as
    # `:name:` so a launcher that cannot draw them still reads sensibly.
    emojis: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any) -> "Announcement | None":
        if not isinstance(data, dict):
            return None
        body = _text(data.get("body"), MAX_BODY_CHARS)
        image = safe_image_url(data.get("image"))
        # A post with neither words nor a picture has nothing to show.
        if not body and not image:
            return None
        return cls(
            id=_text(data.get("id"), 64),
            author=_text(data.get("author"), MAX_NAME_CHARS) or "Announcement",
            avatar=safe_image_url(data.get("avatar")),
            posted=parse_time(data.get("posted")),
            body=body,
            url=safe_url(data.get("url")),
            image=image,
            emojis=emoji_map(data.get("emojis")),
        )


@dataclass
class Video:
    """One upload, whether the relay found it on YouTube or in Discord."""

    id: str = ""
    title: str = ""
    channel: str = ""
    published: datetime | None = None
    url: str = ""
    thumbnail: str = ""
    # "youtube" for a channel upload, "discord" for a link someone posted.
    source: str = "youtube"

    @classmethod
    def from_dict(cls, data: Any) -> "Video | None":
        if not isinstance(data, dict):
            return None
        url = safe_url(data.get("url"))
        title = _text(data.get("title"), MAX_TITLE_CHARS)
        # Without somewhere to send the click the card is decoration.
        if not url or not title:
            return None
        source = _text(data.get("source"), 16).lower()
        return cls(
            id=_text(data.get("id"), 64),
            title=title,
            channel=_text(data.get("channel"), MAX_NAME_CHARS),
            published=parse_time(data.get("published")),
            url=url,
            thumbnail=safe_image_url(data.get("thumbnail")),
            source=source if source in ("youtube", "discord") else "youtube",
        )


@dataclass
class NewsFeed:
    """Everything the news tab shows, as of one fetch."""

    generated: datetime | None = None
    announcements: list[Announcement] = field(default_factory=list)
    videos: list[Video] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.announcements and not self.videos

    @property
    def newest(self) -> datetime | None:
        """The most recent thing in the feed, for the unread marker."""
        moments = [a.posted for a in self.announcements if a.posted]
        moments += [v.published for v in self.videos if v.published]
        return max(moments) if moments else None

    def unread_since(self, seen: datetime | None) -> int:
        """How many items are newer than the last time the page was opened."""
        if seen is None:
            # First run: a brand new install should not open on a badge
            # claiming thirty unread announcements.
            return 0
        items = [a.posted for a in self.announcements] + [
            v.published for v in self.videos
        ]
        return sum(1 for moment in items if moment is not None and moment > seen)

    @classmethod
    def from_dict(cls, data: Any) -> "NewsFeed":
        """Read a feed, keeping whatever parts of it make sense.

        A malformed entry is skipped rather than failing the whole feed: one
        bad announcement should not cost the user their videos.
        """
        if not isinstance(data, dict):
            return cls()
        version = data.get("version")
        if isinstance(version, int) and version > FEED_VERSION:
            # Written by a newer relay than this launcher understands. Refusing
            # is safer than guessing at fields that may have changed meaning.
            return cls()

        announcements: list[Announcement] = []
        for raw in _sequence(data.get("announcements"))[: MAX_ANNOUNCEMENTS * 2]:
            item = Announcement.from_dict(raw)
            if item is not None:
                announcements.append(item)

        videos: list[Video] = []
        seen_urls: set[str] = set()
        for raw in _sequence(data.get("videos"))[: MAX_VIDEOS * 2]:
            item = Video.from_dict(raw)
            # The same video can arrive twice: once from the channel's uploads
            # and again from someone posting the link in Discord.
            if item is None or item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            videos.append(item)

        # Newest first regardless of the order the relay wrote them in. Undated
        # items sort last rather than to the epoch, where they would look like
        # the oldest posts in the room.
        announcements.sort(key=_sort_key_announcement, reverse=True)
        videos.sort(key=_sort_key_video, reverse=True)

        return cls(
            generated=parse_time(data.get("generated")),
            announcements=announcements[:MAX_ANNOUNCEMENTS],
            videos=videos[:MAX_VIDEOS],
        )


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_key_announcement(item: Announcement) -> datetime:
    return item.posted or _EPOCH


def _sort_key_video(item: Video) -> datetime:
    return item.published or _EPOCH


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
