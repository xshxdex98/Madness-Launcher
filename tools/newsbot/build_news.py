"""Build the news.json the launcher reads.

Runs anywhere with a Python 3.9+ interpreter and no third-party packages —
GitHub Actions is the intended home (see news.yml), but it is a plain script
and will run on a laptop or a cron box just as well.

Why this exists at all: Discord has no public, unauthenticated way to read a
channel's messages, and the only alternative to a relay is shipping a bot token
inside the launcher, where anybody who downloads it can pull the token out and
take over the bot. So the token stays here, on a machine you control, and the
launcher only ever fetches the harmless JSON this produces.

    DISCORD_BOT_TOKEN=... python build_news.py --config sources.json --out news.json

Failure is deliberately conservative: if every configured source fails, the
script exits non-zero *without* writing, so a transient outage cannot replace a
good news file with an empty one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEED_VERSION = 1

DISCORD_API = "https://discord.com/api/v10"
YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id="
YOUTUBE_OEMBED = "https://www.youtube.com/oembed"

# Discord asks bots to identify themselves in this shape.
USER_AGENT = (
    "DiscordBot (https://github.com/madness-launcher/newsbot, 1.0) "
    "MadnessLauncherNewsRelay/1.0"
)

MAX_ANNOUNCEMENTS = 25
MAX_VIDEOS = 20
TIMEOUT = 30

# Which YouTube URL shapes count as a video link when one turns up in chat.
_YT_PATTERNS = (
    re.compile(r"youtube\.com/watch\?(?:[^\s]*&)?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/live/([A-Za-z0-9_-]{11})"),
)

_CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")
_CHANNEL_MENTION = re.compile(r"<#(\d+)>")
_ROLE_MENTION = re.compile(r"<@&(\d+)>")
_USER_MENTION = re.compile(r"<@!?(\d+)>")


class SourceError(RuntimeError):
    """One source could not be read. Others may still be fine."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------


def get(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        if exc.code in (401, 403):
            detail = (
                " — check the bot token, and that the bot has been invited to "
                "the server and can read that channel"
            )
        elif exc.code == 429:
            detail = " — rate limited; run the relay less often"
        raise SourceError(f"{url.split('?')[0]} answered {exc.code}{detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"{url.split('?')[0]}: {exc}") from exc


def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    payload = get(url, headers)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceError(f"{url.split('?')[0]} did not return JSON") from exc


# ----------------------------------------------------------------------
# Discord
# ----------------------------------------------------------------------


def discord_messages(channel_id: str, token: str, limit: int) -> list[dict[str, Any]]:
    url = f"{DISCORD_API}/channels/{channel_id}/messages?limit={max(1, min(limit, 100))}"
    data = get_json(url, {"Authorization": f"Bot {token}"})
    if not isinstance(data, list):
        raise SourceError(f"channel {channel_id} returned an unexpected shape")
    return [item for item in data if isinstance(item, dict)]


def author_of(message: dict[str, Any]) -> tuple[str, str]:
    """A display name and avatar URL for whoever posted."""
    author = message.get("author") or {}
    name = (
        author.get("global_name")
        or author.get("username")
        or "Announcement"
    )
    user_id = str(author.get("id") or "")
    avatar = author.get("avatar")
    if user_id and avatar:
        suffix = "gif" if str(avatar).startswith("a_") else "png"
        url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{suffix}?size=64"
    elif user_id.isdigit():
        # Discord's own default avatars, so a post is never faceless.
        index = (int(user_id) >> 22) % 6
        url = f"https://cdn.discordapp.com/embed/avatars/{index}.png"
    else:
        url = ""
    return str(name), url


def readable(message: dict[str, Any]) -> str:
    """Message content with Discord's markup turned into something readable.

    Mentions arrive as raw snowflakes (`<@1234>`), which would otherwise be
    shown to the user verbatim. The names come from the message's own
    `mentions` array, so no extra API calls are needed.
    """
    text = str(message.get("content") or "")

    names = {
        str(user.get("id")): str(user.get("global_name") or user.get("username") or "someone")
        for user in message.get("mentions") or []
        if isinstance(user, dict)
    }
    text = _USER_MENTION.sub(lambda m: "@" + names.get(m.group(1), "someone"), text)
    text = _ROLE_MENTION.sub("@role", text)
    text = _CHANNEL_MENTION.sub("#channel", text)
    text = _CUSTOM_EMOJI.sub(lambda m: f":{m.group(1)}:", text)

    # Announcement posts are very often an embed with an empty content field.
    for embed in message.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        parts = [
            str(embed.get("title") or "").strip(),
            str(embed.get("description") or "").strip(),
        ]
        chunk = "\n".join(part for part in parts if part)
        if chunk:
            text = f"{text}\n\n{chunk}".strip() if text else chunk

    return text.strip()


def image_of(message: dict[str, Any]) -> str:
    """The first picture attached to a post, if there is one."""
    for attachment in message.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        content_type = str(attachment.get("content_type") or "")
        url = str(attachment.get("url") or "")
        if content_type.startswith("image/") and _is_discord_cdn(url):
            return url
    for embed in message.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        for key in ("image", "thumbnail"):
            block = embed.get(key)
            if isinstance(block, dict):
                url = str(block.get("url") or block.get("proxy_url") or "")
                if _is_discord_cdn(url):
                    return url
    return ""


def _is_discord_cdn(url: str) -> bool:
    """The launcher only fetches images from Discord's own CDN — match that."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in ("cdn.discordapp.com", "media.discordapp.net")


def collect_announcements(config: dict[str, Any], token: str) -> tuple[list[dict], int]:
    out: list[dict[str, Any]] = []
    failures = 0
    for source in config.get("announcements") or []:
        channel_id = str(source.get("channel_id") or "").strip()
        guild_id = str(source.get("guild_id") or "").strip()
        if not channel_id:
            continue
        limit = int(source.get("limit") or 15)
        try:
            messages = discord_messages(channel_id, token, limit)
        except SourceError as exc:
            log(f"warning: announcements {channel_id}: {exc}")
            failures += 1
            continue

        for message in messages:
            body = readable(message)
            image = image_of(message)
            if not body and not image:
                continue
            name, avatar = author_of(message)
            message_id = str(message.get("id") or "")
            jump = (
                f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                if guild_id and message_id
                else ""
            )
            out.append(
                {
                    "id": message_id,
                    "author": name,
                    "avatar": avatar,
                    "posted": str(message.get("timestamp") or ""),
                    "body": body,
                    "url": jump,
                    "image": image,
                }
            )
        log(f"announcements {channel_id}: {len(messages)} messages read")
    return out, failures


# ----------------------------------------------------------------------
# YouTube
# ----------------------------------------------------------------------

_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"
_MEDIA = "{http://search.yahoo.com/mrss/}"


def youtube_uploads(channel_id: str, name_override: str = "") -> list[dict[str, Any]]:
    """The channel's recent uploads, from its public Atom feed.

    No API key and no quota: this is the same feed an RSS reader would use.
    It carries the most recent 15 uploads and nothing older, which is exactly
    the window a news tab wants.
    """
    payload = get(YOUTUBE_FEED + urllib.parse.quote(channel_id))
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise SourceError(f"channel {channel_id} feed was not valid XML") from exc

    channel_name = name_override or _text(root.find(f"{_ATOM}title"))
    videos: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry"):
        video_id = _text(entry.find(f"{_YT}videoId"))
        if not video_id:
            continue
        group = entry.find(f"{_MEDIA}group")
        title = _text(entry.find(f"{_ATOM}title"))
        if group is not None and not title:
            title = _text(group.find(f"{_MEDIA}title"))
        author = entry.find(f"{_ATOM}author")
        by = _text(author.find(f"{_ATOM}name")) if author is not None else ""
        videos.append(
            {
                "id": video_id,
                "title": title or "Untitled",
                "channel": name_override or by or channel_name,
                "published": _text(entry.find(f"{_ATOM}published")),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                "source": "youtube",
            }
        )
    return videos


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def youtube_details(video_id: str) -> tuple[str, str]:
    """Title and channel for a bare video ID, via the public oEmbed endpoint.

    Needed for links people paste into Discord, where all we have is the URL.
    Unauthenticated and cheap, but it is one request per new link, so results
    are only looked up for videos not already known from a channel feed.
    """
    url = (
        f"{YOUTUBE_OEMBED}?format=json&url="
        + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
    )
    data = get_json(url)
    if not isinstance(data, dict):
        raise SourceError(f"oembed for {video_id} returned an unexpected shape")
    return str(data.get("title") or "Untitled"), str(data.get("author_name") or "")


def collect_videos(
    config: dict[str, Any], token: str
) -> tuple[list[dict[str, Any]], int]:
    videos: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures = 0

    for source in config.get("youtube") or []:
        channel_id = str(source.get("channel_id") or "").strip()
        if not channel_id:
            continue
        try:
            found = youtube_uploads(channel_id, str(source.get("name") or "").strip())
        except SourceError as exc:
            log(f"warning: youtube {channel_id}: {exc}")
            failures += 1
            continue
        for video in found:
            if video["id"] in seen:
                continue
            seen.add(video["id"])
            videos.append(video)
        log(f"youtube {channel_id}: {len(found)} uploads read")

    # Links people posted in Discord. Anything already known from a channel
    # feed above is skipped, so the common case of "our own video, shared in
    # chat" costs no extra requests and produces no duplicate card.
    for source in config.get("video_channels") or []:
        channel_id = str(source.get("channel_id") or "").strip()
        if not channel_id:
            continue
        try:
            messages = discord_messages(channel_id, token, int(source.get("limit") or 50))
        except SourceError as exc:
            log(f"warning: video channel {channel_id}: {exc}")
            failures += 1
            continue

        added = 0
        for message in messages:
            content = str(message.get("content") or "")
            for video_id in _video_ids(content):
                if video_id in seen:
                    continue
                seen.add(video_id)
                try:
                    title, author = youtube_details(video_id)
                except SourceError as exc:
                    log(f"warning: could not look up {video_id}: {exc}")
                    continue
                videos.append(
                    {
                        "id": video_id,
                        "title": title,
                        "channel": author,
                        # When it was shared, not when it was uploaded: on this
                        # card that is the more useful of the two.
                        "published": str(message.get("timestamp") or ""),
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                        "source": "discord",
                    }
                )
                added += 1
        log(f"video channel {channel_id}: {added} new links found")

    return videos, failures


def _video_ids(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _YT_PATTERNS:
        for match in pattern.finditer(text):
            if match.group(1) not in found:
                found.append(match.group(1))
    return found


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------


def _sort_key(item: dict[str, Any], field: str) -> str:
    """Sort on the raw RFC 3339 string: it sorts correctly as text."""
    return str(item.get(field) or "")


def build(config: dict[str, Any], token: str) -> dict[str, Any]:
    announcements, ann_failures = collect_announcements(config, token)
    videos, vid_failures = collect_videos(config, token)

    configured = len(config.get("announcements") or []) + len(
        config.get("youtube") or []
    ) + len(config.get("video_channels") or [])
    if configured and ann_failures + vid_failures >= configured:
        raise SourceError(
            "every configured source failed; refusing to publish an empty feed"
        )

    announcements.sort(key=lambda item: _sort_key(item, "posted"), reverse=True)
    videos.sort(key=lambda item: _sort_key(item, "published"), reverse=True)

    return {
        "version": FEED_VERSION,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "announcements": announcements[:MAX_ANNOUNCEMENTS],
        "videos": videos[:MAX_VIDEOS],
    }


def resolve_channel(url: str) -> str:
    """Find the UC… ID behind a @handle or /c/ vanity URL.

    Finding this is the fiddliest part of setting the relay up, and the RSS
    feed will only take the canonical ID.
    """
    payload = get(url).decode("utf-8", "replace")
    match = re.search(r'"(?:channelId|externalId)":"(UC[A-Za-z0-9_-]{22})"', payload)
    if not match:
        raise SourceError(f"no channel ID found on {url}")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("sources.json")),
        help="JSON file listing the channels to read (default: sources.json)",
    )
    parser.add_argument("--out", default="news.json", help="where to write the feed")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the feed instead of writing it",
    )
    parser.add_argument(
        "--resolve",
        metavar="URL",
        help="print the UC… channel ID for a YouTube channel URL and exit",
    )
    args = parser.parse_args(argv)

    if args.resolve:
        try:
            print(resolve_channel(args.resolve))
        except SourceError as exc:
            log(f"error: {exc}")
            return 1
        return 0

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"error: could not read {args.config}: {exc}")
        return 1

    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    needs_token = bool(config.get("announcements") or config.get("video_channels"))
    if needs_token and not token:
        log("error: DISCORD_BOT_TOKEN is not set, and Discord sources are configured")
        return 1

    try:
        feed = build(config, token)
    except SourceError as exc:
        log(f"error: {exc}")
        return 1

    rendered = json.dumps(feed, indent=2, ensure_ascii=False) + "\n"
    if args.dry_run:
        print(rendered)
        return 0

    Path(args.out).write_text(rendered, encoding="utf-8")
    log(
        f"wrote {args.out}: {len(feed['announcements'])} announcements, "
        f"{len(feed['videos'])} videos"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
