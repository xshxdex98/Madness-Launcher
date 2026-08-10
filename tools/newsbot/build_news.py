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
import time
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
# Room for every configured channel to be properly represented. Four channels
# publishing fifteen uploads each is sixty candidates, and a cap much below
# this starts deciding which channels exist rather than merely how far back
# the tab goes.
MAX_VIDEOS = 40
TIMEOUT = 30

# Which YouTube URL shapes count as a video link when one turns up in chat.
_YT_PATTERNS = (
    re.compile(r"youtube\.com/watch\?(?:[^\s]*&)?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/live/([A-Za-z0-9_-]{11})"),
)

# Which uploads count as being about the six games the launcher supports.
# Matched against the video's title with word boundaries, case-insensitively.
# Overridable per-deployment in sources.json — keep them here as the fallback
# so a config that omits the block still filters rather than letting the tab
# fill with whatever else a channel happens to post.
DEFAULT_VIDEO_MATCH = [
    "midtown madness",
    "monster truck madness",
    "motocross madness",
    "mm1", "mm2",
    "mtm", "mtm1", "mtm2",
    "mcm", "mcm1", "mcm2",
    # The Midtown Madness 2 source port the launcher builds its support on,
    # and the community that gathers around it.
    "open1560",
    "midtown club",
    "madness crew",
]

# Checked first, and a hit rejects outright. "Madness" is a common word in
# game titles that have nothing to do with these six, and Madness Combat in
# particular is popular enough to swamp the tab on its own.
DEFAULT_VIDEO_EXCLUDE = [
    "madness combat",
    "madness project nexus",
    "march madness",
    "madness returns",
    "bloody roar",
]

_CUSTOM_EMOJI = re.compile(r"<a?:(\w+):(\d+)>")
# Matches the launcher's own rule, so a name the relay emits is always one the
# launcher will accept as a substitution key.
_EMOJI_NAME = re.compile(r"\w{1,32}")
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


def guild_roles(guild_id: str, token: str, cache: dict[str, dict[str, str]]) -> dict[str, str]:
    """`{role id: role name}` for a server, fetched at most once per run.

    Messages carry the IDs of the roles they ping but not the names, so
    without this every `@everyone`-style role mention in an announcement
    reaches the launcher as a bare "@role".
    """
    if guild_id in cache:
        return cache[guild_id]
    roles: dict[str, str] = {}
    if guild_id:
        try:
            data = get_json(
                f"{DISCORD_API}/guilds/{guild_id}/roles",
                {"Authorization": f"Bot {token}"},
            )
        except SourceError as exc:
            # Not fatal: the posts are still worth publishing without it.
            log(f"warning: could not read roles for guild {guild_id}: {exc}")
            data = []
        for role in data if isinstance(data, list) else []:
            if isinstance(role, dict) and role.get("id"):
                roles[str(role["id"])] = str(role.get("name") or "role")
    cache[guild_id] = roles
    return roles


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


def readable(
    message: dict[str, Any],
    roles: dict[str, str] | None = None,
    emojis: dict[str, str] | None = None,
) -> str:
    """Message content with Discord's markup turned into something readable.

    Mentions arrive as raw snowflakes (`<@1234>`), which would otherwise be
    shown to the user verbatim. User names come from the message's own
    `mentions` array; role names come from `roles`, which the caller fetches
    once per server.

    Custom emoji are left in the body as `:name:` and their image URLs
    collected into `emojis` rather than being substituted inline. A launcher
    that cannot draw them still reads correctly, and the feed stays plain text.
    """
    text = str(message.get("content") or "")
    roles = roles or {}

    names = {
        str(user.get("id")): str(user.get("global_name") or user.get("username") or "someone")
        for user in message.get("mentions") or []
        if isinstance(user, dict)
    }
    text = _USER_MENTION.sub(lambda m: "@" + names.get(m.group(1), "someone"), text)
    text = _ROLE_MENTION.sub(lambda m: "@" + roles.get(m.group(1), "role"), text)
    text = _CHANNEL_MENTION.sub("#channel", text)

    def emoji(match: re.Match[str]) -> str:
        name, emoji_id, animated = match.group(1), match.group(2), match.group(0)[1] == "a"
        if emojis is not None and _EMOJI_NAME.fullmatch(name):
            suffix = "gif" if animated else "png"
            emojis[name] = f"https://cdn.discordapp.com/emojis/{emoji_id}.{suffix}"
        return f":{name}:"

    text = _CUSTOM_EMOJI.sub(emoji, text)

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
    role_cache: dict[str, dict[str, str]] = {}
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

        roles = guild_roles(guild_id, token, role_cache)
        for message in messages:
            emojis: dict[str, str] = {}
            body = readable(message, roles, emojis)
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
                    "emojis": emojis,
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
    vfilter = VideoFilter(config)

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
        # A channel that only ever posts about these games can opt out, rather
        # than having every title second-guessed by a keyword list.
        screen = source.get("filter", True) is not False
        kept = 0
        for video in found:
            if video["id"] in seen:
                continue
            if screen and not vfilter.allows(video["title"]):
                # Named, not just counted: a filter nobody can see the effect
                # of is a filter nobody can tune.
                log(f"  filtered out: {video['title'][:70]}")
                continue
            seen.add(video["id"])
            videos.append(video)
            kept += 1
        log(f"youtube {channel_id}: {len(found)} uploads read, {kept} kept")

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

        screen = source.get("filter", True) is not False
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
                # The title is only known after the lookup, so a shared link
                # costs one request even when it is then filtered out.
                if screen and not vfilter.allows(title):
                    log(f"  filtered out (shared): {title[:70]}")
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
# Lap records
# ----------------------------------------------------------------------

# The launcher posts one line of key="value" pairs under a human-readable
# headline. Parsed back out here rather than from the headline, which exists
# for people scrolling the channel.
_RECORD_FIELD = re.compile(r'(\w{1,12})="([^"]{0,120})"')
_RECORD_REQUIRED = ("game", "board", "race", "time")

MAX_BOARD_RECORDS = 600
BOARDS = ("vanilla", "modded")

# The same bounds the launcher applies before sending. Re-checked here because
# the webhook URL is extractable from the executable, so a message in the
# channel is not proof that the launcher wrote it.
MIN_RECORD_SECONDS = 8.0
MAX_RECORD_SECONDS = 3600.0


def parse_record(message: dict[str, Any]) -> dict[str, Any] | None:
    """One lap record out of a channel message, or None if it is not one."""
    content = str(message.get("content") or "")
    fields = dict(_RECORD_FIELD.findall(content))
    if not all(k in fields for k in _RECORD_REQUIRED):
        return None
    try:
        seconds = float(fields["time"])
        race = int(fields["race"])
    except (TypeError, ValueError):
        return None
    if not (MIN_RECORD_SECONDS <= seconds <= MAX_RECORD_SECONDS):
        return None
    if fields["board"] not in BOARDS or race < 0 or race > 999:
        return None
    return {
        "game": fields["game"][:16],
        "board": fields["board"],
        "race": race,
        "race_name": fields.get("name", "")[:80],
        "race_kind": fields.get("kind", "")[:16],
        "difficulty": fields.get("diff", "")[:16],
        "car": fields.get("car", "")[:40],
        "seconds": round(seconds, 3),
        "username": fields.get("by", "")[:40],
        "set_at": fields.get("at", "")[:32],
        # Kept so a disputed entry can be found and deleted in Discord.
        "message_id": str(message.get("id") or ""),
    }


def collect_records(config: dict[str, Any], token: str) -> tuple[list[dict], int]:
    """The best claimed time per race, per board, per difficulty.

    Only the fastest survives each slot, so the channel can hold every
    attempt anyone ever posted and the board stays a board. Deleting the
    message behind a bogus entry is what removes it: the next run simply does
    not see it, and the next-best time takes the slot back.
    """
    best: dict[tuple, dict] = {}
    failures = 0
    seen = 0
    for source in config.get("records") or []:
        channel_id = str(source.get("channel_id") or "").strip()
        if not channel_id:
            continue
        try:
            messages = discord_messages(channel_id, token, int(source.get("limit") or 100))
        except SourceError as exc:
            log(f"warning: records {channel_id}: {exc}")
            failures += 1
            continue
        for message in messages:
            record = parse_record(message)
            if record is None:
                continue
            seen += 1
            key = (record["game"], record["board"], record["difficulty"], record["race"])
            current = best.get(key)
            if current is None or record["seconds"] < current["seconds"]:
                best[key] = record
        log(f"records {channel_id}: {len(messages)} messages, {seen} records")

    out = sorted(
        best.values(), key=lambda r: (r["game"], r["board"], r["race"], r["difficulty"])
    )
    return out[:MAX_BOARD_RECORDS], failures


# ----------------------------------------------------------------------
# speedrun.com
# ----------------------------------------------------------------------

SPEEDRUN_API = "https://www.speedrun.com/api/v1"

# The site asks for roughly one request a second and will start refusing
# otherwise. Fetched here once per run rather than from every launcher, which
# is both faster for users and the only polite way to do it.
SPEEDRUN_DELAY = 0.7

# Per-level categories worth publishing. These are the two the game itself
# keeps tables for, so they line up with amateur.dat and pro.dat.
SPEEDRUN_CATEGORIES = ("Amateur", "Professional")

_DIFFICULTY_FROM_CATEGORY = {"amateur": "amateur", "professional": "pro"}


def speedrun_records(config: dict[str, Any]) -> tuple[list[dict], int]:
    """World records per race from speedrun.com's own leaderboards.

    Published alongside community submissions rather than mixed into them.
    A run there has been checked by that game's moderators against video, so
    it is a stronger claim than anything this system can make on its own —
    but it is somebody else's data, and it is labelled as such.

    Races are carried by NAME, never by position. speedrun.com lists them
    Blitz, Checkpoint, Circuit and the game orders them Blitz, Circuit,
    Checkpoint, so publishing an index here would file every Circuit record
    under a Checkpoint race.
    """
    block = config.get("speedrun")
    block = block if isinstance(block, dict) else {}
    if block.get("enabled") is not True:
        return [], 0

    abbreviation = str(block.get("game") or "midtown1")
    wanted = [str(c) for c in (block.get("categories") or SPEEDRUN_CATEGORIES)]
    game_key = str(block.get("board_game") or "mm1")

    def api(path: str) -> Any:
        time.sleep(SPEEDRUN_DELAY)
        return get_json(f"{SPEEDRUN_API}/{path}")

    try:
        games = api(f"games?abbreviation={urllib.parse.quote(abbreviation)}")["data"]
        if not games:
            raise SourceError(f"no game called {abbreviation!r}")
        game_id = games[0]["id"]
        levels = api(f"games/{game_id}/levels")["data"]
        categories = [
            c for c in api(f"games/{game_id}/categories")["data"]
            if c.get("type") == "per-level" and c.get("name") in wanted
        ]
    except (SourceError, KeyError, IndexError, TypeError) as exc:
        log(f"warning: speedrun.com lookup failed: {exc}")
        return [], 1

    if not levels or not categories:
        log("warning: speedrun.com returned no levels or no matching categories")
        return [], 1

    out: list[dict[str, Any]] = []
    failures = 0
    for level in levels:
        for category in categories:
            try:
                board = api(
                    f"leaderboards/{game_id}/level/{level['id']}/{category['id']}"
                    "?top=1&embed=players"
                )["data"]
            except (SourceError, KeyError, TypeError) as exc:
                log(f"warning: speedrun.com {level.get('name')}: {exc}")
                failures += 1
                continue

            runs = board.get("runs") or []
            if not runs:
                continue
            run = runs[0].get("run") or {}
            seconds = (run.get("times") or {}).get("primary_t")
            if not isinstance(seconds, (int, float)) or not (
                MIN_RECORD_SECONDS <= seconds <= MAX_RECORD_SECONDS
            ):
                continue

            named = {
                p["id"]: (p.get("names") or {}).get("international") or p.get("name")
                for p in (board.get("players") or {}).get("data", [])
                if isinstance(p, dict) and p.get("id")
            }
            who = ", ".join(
                str(named.get(p.get("id")) or p.get("name") or "Anonymous")
                for p in (run.get("players") or [])
            ) or "Anonymous"

            out.append({
                "game": game_key,
                # A verified run on the stock game is a vanilla record.
                "board": "vanilla",
                "race": -1,
                "race_name": str(level.get("name") or "")[:80],
                "difficulty": _DIFFICULTY_FROM_CATEGORY.get(
                    str(category.get("name", "")).lower(), ""
                ),
                "seconds": round(float(seconds), 3),
                "username": who[:40],
                "set_at": str(run.get("date") or ""),
                "source": "speedrun.com",
                "url": str(run.get("weblink") or "")[:200],
            })

    log(f"speedrun.com: {len(out)} records across {len(levels)} races")
    return out, failures


# ----------------------------------------------------------------------
# Assembly
# ----------------------------------------------------------------------


def _compile(patterns: Any, fallback: list[str]) -> list[re.Pattern[str]]:
    """Turn plain phrases into title matchers.

    The words of a phrase are allowed to run together, because a title is as
    likely to say "#midtownmadness" as "Midtown Madness" — hashtags carry no
    spaces, and on Shorts the hashtag is often the only mention of the game
    anywhere in the title. Written as a separator class rather than a second
    keyword so the config stays readable and nobody has to remember to add
    both spellings of every term.

    Word boundaries at the edges keep "mm2" out of "mm2020" while still
    matching "MM2: Revisited" and "#mm2".
    """
    out: list[re.Pattern[str]] = []
    for raw in patterns or fallback:
        if not isinstance(raw, str) or not raw.strip():
            continue
        words = [re.escape(w) for w in re.split(r"[\s\-_]+", raw.strip()) if w]
        if not words:
            continue
        out.append(re.compile(r"\b" + r"[\W_]*".join(words) + r"\b", re.IGNORECASE))
    return out


class VideoFilter:
    """Decides whether an upload is about one of the launcher's six games.

    Judged on the title alone. Matching the channel name too would mean a
    channel called anything with "Madness" in it passed everything it ever
    posted, which is the opposite of what a filter is for — a channel that
    should be trusted wholesale says so explicitly with "filter": false on
    its own entry instead.
    """

    def __init__(self, config: dict[str, Any]):
        block = config.get("video_filter")
        block = block if isinstance(block, dict) else {}
        self.enabled = block.get("enabled", True) is not False
        self.match = _compile(block.get("match"), DEFAULT_VIDEO_MATCH)
        self.exclude = _compile(block.get("exclude"), DEFAULT_VIDEO_EXCLUDE)

    def allows(self, title: str) -> bool:
        if not self.enabled:
            return True
        if any(p.search(title) for p in self.exclude):
            return False
        return any(p.search(title) for p in self.match)


def _sort_key(item: dict[str, Any], field: str) -> str:
    """Sort on the raw RFC 3339 string: it sorts correctly as text."""
    return str(item.get(field) or "")


def balanced(videos: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Trim to `limit`, giving every channel a turn before any gets seconds.

    A plain newest-first cut is not neutral between channels. A prolific one
    fills the list and a quieter one vanishes from the tab altogether, which
    reads as the launcher having forgotten that channel rather than as a cap
    being reached — exactly what happened with four channels and a cap of
    twenty: two of them disappeared.

    Selection is round-robin by recency; the result is re-sorted by date, so
    the tab still reads newest-first and only the choice of *which* uploads
    survive is balanced.
    """
    if len(videos) <= limit:
        return videos

    by_channel: dict[str, list[dict[str, Any]]] = {}
    for video in videos:
        by_channel.setdefault(str(video.get("channel") or ""), []).append(video)
    for group in by_channel.values():
        group.sort(key=lambda item: _sort_key(item, "published"), reverse=True)

    picked: list[dict[str, Any]] = []
    queues = list(by_channel.values())
    while len(picked) < limit and any(queues):
        for queue in queues:
            if queue:
                picked.append(queue.pop(0))
                if len(picked) >= limit:
                    break

    log(
        f"videos: kept {len(picked)} of {len(videos)} across "
        f"{len(by_channel)} channels (cap {limit})"
    )
    picked.sort(key=lambda item: _sort_key(item, "published"), reverse=True)
    return picked


def build(config: dict[str, Any], token: str) -> dict[str, Any]:
    announcements, ann_failures = collect_announcements(config, token)
    videos, vid_failures = collect_videos(config, token)
    records, _ = collect_records(config, token)
    external, _ = speedrun_records(config)
    # Appended rather than merged into the same slots: an external record
    # and a community one are different claims and the tab shows both.
    records = records + external

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
        "videos": balanced(videos, MAX_VIDEOS),
        "records": records,
        # Where launchers post a new record. Published here so it can be
        # rotated after abuse without shipping a new build.
        "records_webhook": str(config.get("records_webhook") or ""),
    }


# The page's own identity. Both of these name the channel being viewed;
# "channelId" on its own does NOT — a channel page carries a dozen of them for
# recommended channels and video owners, and the first is somebody else's.
_CANONICAL_ID = re.compile(
    r'rel="canonical"\s+href="https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"'
)
_EXTERNAL_ID = re.compile(r'"externalId":"(UC[A-Za-z0-9_-]{22})"')


def resolve_channel(url: str) -> str:
    """Find the UC… ID behind a @handle or /c/ vanity URL.

    Finding this is the fiddliest part of setting the relay up, and the RSS
    feed will only take the canonical ID.
    """
    payload = get(url).decode("utf-8", "replace")
    for pattern in (_CANONICAL_ID, _EXTERNAL_ID):
        match = pattern.search(payload)
        if match:
            return match.group(1)
    raise SourceError(f"no channel ID found on {url}")


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
        f"{len(feed['videos'])} videos, {len(feed['records'])} records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
