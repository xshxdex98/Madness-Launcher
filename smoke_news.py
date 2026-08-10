"""Checks for the News tab and the relay that feeds it.

Entirely offline. The feed is the one part of the launcher whose input comes
from the internet, so the interesting cases are all about a feed that is wrong
rather than one that is right: a hostile URL, a missing field, a body of the
wrong type. None of that can be exercised by pointing it at the real news file
and seeing that it looks fine.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "newsbot"))

SANDBOX = Path(tempfile.mkdtemp(prefix="madness-news-"))
os.environ["MADNESS_LAUNCHER_HOME"] = str(SANDBOX)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

# Settings warns with a modal when the URL is unusable, and a modal in an
# offscreen run waits forever for a button nobody can press. Recorded instead,
# so the checks below can assert that the user was actually told.
warnings_shown: list[str] = []
QMessageBox.warning = staticmethod(  # type: ignore[method-assign]
    lambda parent, title, text, *args, **kwargs: warnings_shown.append(str(title))
)

import build_news  # noqa: E402
from madness_launcher.config import Config  # noqa: E402
from madness_launcher.news import NewsFeed, NewsService, ThumbnailCache  # noqa: E402
from madness_launcher.news.model import age_of, safe_image_url, safe_url  # noqa: E402
from madness_launcher.ui import theme  # noqa: E402
from madness_launcher.ui.main_window import NEWS_KEY, MainWindow  # noqa: E402
from madness_launcher.ui.news_page import NewsPage, to_rich_text  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(theme.stylesheet())

NOW = datetime.now(timezone.utc)


def stamp(**kwargs) -> str:
    return (NOW - timedelta(**kwargs)).strftime("%Y-%m-%dT%H:%M:%SZ")


SAMPLE = {
    "version": 1,
    "generated": stamp(minutes=2),
    "announcements": [
        {
            "id": "1",
            "author": "Robin",
            "avatar": "https://cdn.discordapp.com/avatars/1/abc.png",
            "posted": stamp(hours=3),
            "body": "Server is back up. See https://example.com for details.",
            "url": "https://discord.com/channels/1/2/3",
            "image": "",
        },
        {
            "id": "2",
            "author": "Someone",
            "posted": stamp(days=2),
            "body": "**Patch 1.2** is out.",
            "image": "https://cdn.discordapp.com/attachments/1/2/shot.png",
        },
    ],
    "videos": [
        {
            "id": "aaaaaaaaaaa",
            "title": "Midtown Madness in 2026",
            "channel": "Someone",
            "published": stamp(days=1),
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "thumbnail": "https://i.ytimg.com/vi/aaaaaaaaaaa/mqdefault.jpg",
            "source": "youtube",
        },
        {
            "id": "bbbbbbbbbbb",
            "title": "Someone else's run",
            "channel": "A Channel",
            "published": stamp(days=4),
            "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            "thumbnail": "https://i.ytimg.com/vi/bbbbbbbbbbb/mqdefault.jpg",
            "source": "discord",
        },
    ],
}


print("a well-formed feed reads back intact")
feed = NewsFeed.from_dict(SAMPLE)
check("both announcements survive", len(feed.announcements) == 2,
      str(len(feed.announcements)))
check("both videos survive", len(feed.videos) == 2, str(len(feed.videos)))
check("not empty", not feed.is_empty)
check("newest item is the 3-hour-old post",
      feed.newest is not None and (NOW - feed.newest) < timedelta(hours=4))
check("announcements are newest first",
      feed.announcements[0].id == "1", feed.announcements[0].id)
check("videos are newest first",
      feed.videos[0].id == "aaaaaaaaaaa", feed.videos[0].id)
check("the shared video keeps its source", feed.videos[1].source == "discord")


print("\nURLs from a feed are not taken on trust")
for hostile in (
    "javascript:alert(1)",
    "file:///C:/Windows/System32/calc.exe",
    "data:text/html,<script>x</script>",
    "ftp://example.com/x",
    "",
    None,
    12345,
    "http://" + "a" * 4000,
):
    check(f"rejected: {str(hostile)[:38]!r}", safe_url(hostile) == "")
check("plain https is allowed", safe_url("https://example.com/x") != "")
check("plain http is allowed", safe_url("http://example.com/x") != "")

print("\nimages may only come from the hosts we expect")
check("youtube thumbnails allowed",
      safe_image_url("https://i.ytimg.com/vi/x/mqdefault.jpg") != "")
check("discord cdn allowed",
      safe_image_url("https://cdn.discordapp.com/attachments/1/2/a.png") != "")
check("anywhere else refused",
      safe_image_url("https://tracker.example.com/pixel.png") == "")
check("lookalike host refused",
      safe_image_url("https://i.ytimg.com.evil.test/x.jpg") == "")


print("\na broken feed loses only the broken parts")
messy = {
    "version": 1,
    "announcements": [
        {"body": "fine"},
        "not a dict",
        {"body": 42},
        {},
        {"body": "also fine", "image": "https://evil.test/x.png"},
    ],
    "videos": [
        {"title": "no url"},
        {"url": "https://www.youtube.com/watch?v=x", "title": "kept"},
        None,
    ],
}
salvaged = NewsFeed.from_dict(messy)
check("two readable announcements kept", len(salvaged.announcements) == 2,
      str(len(salvaged.announcements)))
check("the disallowed image was dropped, the post kept",
      salvaged.announcements[-1].image == "" or salvaged.announcements[0].image == "")
check("one readable video kept", len(salvaged.videos) == 1,
      str(len(salvaged.videos)))
check("a video with no URL is not shown",
      all(v.url for v in salvaged.videos))

print("\nnonsense at the top level does not raise")
for junk in (None, [], "a string", 7, {"announcements": "nope"}):
    try:
        result = NewsFeed.from_dict(junk)
        check(f"survives {str(junk)[:24]!r}", result.is_empty)
    except Exception as exc:  # noqa: BLE001 - that is the thing being tested
        check(f"survives {str(junk)[:24]!r}", False, repr(exc))

print("\na feed from a newer relay is declined rather than guessed at")
check("version 2 is not read", NewsFeed.from_dict({**SAMPLE, "version": 2}).is_empty)
check("an unknown extra field is ignored, not fatal",
      not NewsFeed.from_dict({**SAMPLE, "banner": {"x": 1}}).is_empty)

print("\nthe same video from two sources appears once")
doubled = NewsFeed.from_dict(
    {
        "version": 1,
        "videos": [
            {"url": "https://www.youtube.com/watch?v=zzz", "title": "Upload",
             "source": "youtube", "published": stamp(hours=2)},
            {"url": "https://www.youtube.com/watch?v=zzz", "title": "Upload",
             "source": "discord", "published": stamp(hours=1)},
        ],
    }
)
check("deduplicated by URL", len(doubled.videos) == 1, str(len(doubled.videos)))


print("\nages read the way a person would say them")
cases = {
    timedelta(seconds=5): "just now",
    timedelta(minutes=1): "just now",
    timedelta(minutes=5): "5 minutes ago",
    timedelta(hours=1, minutes=1): "1 hour ago",
    timedelta(hours=5): "5 hours ago",
    timedelta(days=1, hours=1): "1 day ago",
    timedelta(days=3): "3 days ago",
}
for delta, expected in cases.items():
    got = age_of(NOW - delta, now=NOW)
    check(f"{delta} reads {expected!r}", got == expected, repr(got))
check("no timestamp reads as nothing", age_of(None) == "")
check("a future timestamp does not read as negative",
      age_of(NOW + timedelta(hours=2), now=NOW) == "just now")
check("beyond a week becomes a date",
      "ago" not in age_of(NOW - timedelta(days=40), now=NOW))

print("\nsingular and plural")
check("one minute", age_of(NOW - timedelta(minutes=1, seconds=40), now=NOW)
      == "1 minute ago")
check("two minutes", age_of(NOW - timedelta(minutes=2), now=NOW) == "2 minutes ago")


print("\nbody text is escaped before anything is rendered")
nasty = to_rich_text('<script>alert("x")</script> & <b>raw</b>')
check("no live script tag", "<script>" not in nasty, nasty)
check("angle brackets escaped", "&lt;script&gt;" in nasty, nasty)
check("ampersand escaped", "&amp;" in nasty, nasty)
check("no injected bold", "<b>raw</b>" not in nasty, nasty)

print("\nlinks and light formatting are restored")
rich = to_rich_text("See https://example.com/a?x=1&y=2 now")
check("a link is produced", '<a href="https://example.com/a?x=1&amp;y=2"' in rich, rich)
check("bold works", "<b>hi</b>" in to_rich_text("**hi**"))
check("italic works", "<i>hi</i>" in to_rich_text("*hi*"))
check("newlines become breaks", "<br>" in to_rich_text("a\nb"))
check("a heading loses its hashes",
      "# Big news" not in to_rich_text("# Big news")
      and ">Big news<" in to_rich_text("# Big news"),
      to_rich_text("# Big news"))
check("a heading is enlarged", "17px" in to_rich_text("# Big news"),
      to_rich_text("# Big news"))
check("a sub-heading is smaller", "15px" in to_rich_text("## Less big"),
      to_rich_text("## Less big"))
check("a hash mid-sentence is left alone",
      "C# is a language" in to_rich_text("C# is a language"))
check("a hash with no space is not a heading",
      "#1" in to_rich_text("#1 in the charts"))
check(
    "trailing punctuation stays out of the link",
    to_rich_text("go to https://example.com.").endswith("</a>."),
    to_rich_text("go to https://example.com."),
)
check(
    "a link inside text is not left raw",
    "javascript" not in to_rich_text("javascript:alert(1)").lower()
    or "<a " not in to_rich_text("javascript:alert(1)"),
)


print("\ncustom emoji become images once their file is on disk")
EMOJI = {"MADNESSCREW": "https://cdn.discordapp.com/emojis/123.png"}
never = to_rich_text("nice :MADNESSCREW: run", EMOJI, lambda url: "")
check("still readable while the image is downloading",
      ":MADNESSCREW:" in never and "<img" not in never, never)
landed = to_rich_text("nice :MADNESSCREW: run", EMOJI, lambda url: "C:/cache/abc")
check("swapped for an img once it has landed", "<img src=\"C:/cache/abc\"" in landed,
      landed)
check("and sized so the line does not grow", 'width="18"' in landed, landed)
check("an emoji the post never declared is left alone",
      ":unknown:" in to_rich_text(":unknown:", EMOJI, lambda url: "C:/cache/abc"))
check("no emoji map means no substitution",
      ":MADNESSCREW:" in to_rich_text("nice :MADNESSCREW: run"))

print("\nan emoji name is not a way to inject markup")
from madness_launcher.news.model import emoji_map  # noqa: E402

check("a name with markup is rejected",
      emoji_map({'x" onerror="alert(1)': "https://cdn.discordapp.com/emojis/1.png"})
      == {})
check("a name with a space is rejected",
      emoji_map({"two words": "https://cdn.discordapp.com/emojis/1.png"}) == {})
check("an off-CDN emoji URL is rejected",
      emoji_map({"evil": "https://evil.test/x.png"}) == {})
check("a normal one is kept",
      emoji_map({"mm1": "https://cdn.discordapp.com/emojis/1.png"}) != {})
check("not a dict is survived", emoji_map("nope") == {})
check("the count is capped",
      len(emoji_map({f"e{i}": "https://cdn.discordapp.com/emojis/1.png"
                     for i in range(80)})) <= 32)
hostile_path = to_rich_text(
    ":mm1:", {"mm1": "https://cdn.discordapp.com/emojis/1.png"},
    lambda url: 'x" onerror="alert(1)',
)
check("a path with a quote in it cannot break out of the attribute",
      '" onerror="' not in hostile_path and "&quot;" in hostile_path,
      hostile_path)

print("\nunread counting")
seen_all = feed.newest
check("nothing unread once everything is seen",
      feed.unread_since(seen_all) == 0, str(feed.unread_since(seen_all)))
check("a fresh install starts at zero, not at everything",
      feed.unread_since(None) == 0, str(feed.unread_since(None)))
check("two items are newer than three days ago",
      feed.unread_since(NOW - timedelta(days=3)) == 3,
      str(feed.unread_since(NOW - timedelta(days=3))))


print("\nthe service caches to disk and reads it back")
config = Config()
config.settings.news_url = "https://invalid.test/news.json"
service = NewsService(config)
check("nothing cached on a fresh install", service.feed.is_empty)
check("state starts idle", service.state == "idle", service.state)

from madness_launcher.news import service as service_module  # noqa: E402

service_module.cache_dir().mkdir(parents=True, exist_ok=True)
service_module.feed_file().write_text(json.dumps(SAMPLE), encoding="utf-8")
service_module.meta_file().write_text(
    json.dumps(
        {
            "etag": '"abc"',
            "last_modified": "",
            "url": "https://invalid.test/news.json",
            "fetched_at": stamp(minutes=30),
        }
    ),
    encoding="utf-8",
)
reloaded = NewsService(config)
check("the cached feed is read at startup", len(reloaded.feed.announcements) == 2,
      str(len(reloaded.feed.announcements)))
check("and is marked as possibly out of date", reloaded.state == "stale",
      reloaded.state)
check("the ETag is reused", reloaded._validators()[0] == '"abc"',
      repr(reloaded._validators()))

print("\nvalidators are not reused across a change of source")
config.settings.news_url = "https://elsewhere.test/news.json"
moved = NewsService(config)
check("a different URL revalidates from scratch", moved._validators() == ("", ""),
      repr(moved._validators()))
config.settings.news_url = "https://invalid.test/news.json"

print("\na corrupt cache is ignored rather than fatal")
service_module.feed_file().write_text("{not json", encoding="utf-8")
check("construction still succeeds", NewsService(config).feed.is_empty)
service_module.feed_file().write_text(json.dumps(SAMPLE), encoding="utf-8")

print("\nrefreshing is throttled, but the button always works")
throttled = NewsService(config)
throttled.refresh()
first = throttled._last_attempt
throttled.stop()
throttled.refresh()
check("a second immediate refresh is skipped", throttled._last_attempt == first)
throttled.refresh(force=True)
check("forcing goes through", throttled._last_attempt != first)
throttled.stop()

print("\nwith no URL set the service says so instead of dialling out")
blank = Config()
blank.settings.news_url = ""
unset = NewsService(blank)
unset.refresh()
check("state is unset", unset.state == "unset", unset.state)
check("nothing is in flight", unset._reply is None)


print("\nmarking as seen is remembered")
config.settings.news_last_seen = ""
marker = NewsService(config)
check("everything is unread against an explicit old date",
      marker.feed.unread_since(NOW - timedelta(days=10)) == 4,
      str(marker.feed.unread_since(NOW - timedelta(days=10))))
marker.mark_seen()
check("the newest timestamp is stored", config.settings.news_last_seen != "")
check("nothing is unread afterwards", marker.unread() == 0, str(marker.unread()))
before = config.settings.news_last_seen
marker.mark_seen()
check("marking again does not move it backwards",
      config.settings.news_last_seen == before)


print("\nthe page draws the feed without a network")
thumbs = ThumbnailCache()
page = NewsPage(marker, thumbs)
check("announcements tab is populated",
      page.announcement_column.count() == 2, str(page.announcement_column.count()))
check("videos tab is populated",
      page.video_column.count() == 2, str(page.video_column.count()))
check("tab labels carry counts", "2" in page.tabs.tabText(0), page.tabs.tabText(0))

print("\nand says something useful when there is nothing to draw")
empty_page = NewsPage(NewsService(blank), thumbs)
check("an empty announcements tab still has a notice",
      empty_page.announcement_column.count() == 1)
check("the unset state is explained, not blamed on the network",
      "Settings" in empty_page.status_label.text(),
      empty_page.status_label.text())
check("refresh is disabled with nowhere to refresh from",
      not empty_page.refresh_button.isEnabled())

print("\na cached feed that cannot be refreshed reads as old, not as broken")
stale = NewsService(config)
stale._fail("the network is down")
check("state is stale while a feed is on screen", stale.state == "stale", stale.state)
stale_page = NewsPage(stale, thumbs)
check("the page says it is showing older news",
      "Showing news from" in stale_page.status_label.text(),
      stale_page.status_label.text())

empty_and_failing = NewsService(blank)
empty_and_failing.config.settings.news_url = "https://invalid.test/news.json"
empty_and_failing._fail("the network is down")
check("with nothing cached the same failure is an error",
      empty_and_failing.state == "error", empty_and_failing.state)


print("\nthe sidebar carries the unread marker")
window_config = Config()
window_config.settings.news_url = "https://invalid.test/news.json"
window_config.settings.chat_host = "invalid.test"
window_config.settings.show_online_count = False
window = MainWindow(window_config)
window.news._feed = NewsFeed.from_dict(SAMPLE)
window.config.settings.news_last_seen = (NOW - timedelta(days=3)).isoformat()
window._refresh_news_entry()
check("the count is shown on the entry", "3" in window.news_entry.text(),
      window.news_entry.text())
check("the tooltip explains it", "new post" in window.news_entry.toolTip(),
      window.news_entry.toolTip())

window._show(NEWS_KEY)
check("opening the tab builds the page", window._news is not None)
check("opening the tab clears the marker",
      window.news_entry.text().strip() == "News", window.news_entry.text())
check("the entry is selected", window.news_entry.isChecked())

print("\nan unreachable source is reported on the entry, not hidden")
window.news._feed = NewsFeed()
window.news._error = "Host invalid.test not found"
window.news._set_state("error")
window._refresh_news_entry()
check("the tooltip carries the reason",
      "invalid.test" in window.news_entry.toolTip(), window.news_entry.toolTip())

print("\na bad URL typed into Settings is refused before it is saved")
window._show("__settings__")
warnings_shown.clear()
window.news_url_field.setText("nonsense")
window._save_news_url()
check("the setting was not overwritten",
      window.config.settings.news_url == "https://invalid.test/news.json",
      window.config.settings.news_url)
check("and the user was told why", len(warnings_shown) == 1, str(warnings_shown))
check("the field is put back to the saved value",
      window.news_url_field.text() == "https://invalid.test/news.json",
      window.news_url_field.text())
window.news_url_field.setText("https://example.com/news.json")
window._save_news_url()
check("a good URL is accepted",
      window.config.settings.news_url == "https://example.com/news.json",
      window.config.settings.news_url)
window.news_url_field.setText("")
window._save_news_url()
check("clearing it is allowed", window.config.settings.news_url == "")

window.close()
check("closing leaves nothing in flight", window.news._reply is None)


# ----------------------------------------------------------------------
# The relay
# ----------------------------------------------------------------------

print("\nthe relay turns Discord's markup into something readable")
message = {
    "content": "Hey <@111> and <@!222>, see <#333> — <@&444> <:madness:555> ping",
    "mentions": [
        {"id": "111", "global_name": "Robin"},
        {"id": "222", "username": "someone"},
    ],
}
emoji_out: dict[str, str] = {}
readable = build_news.readable(
    message, {"444": "Madness Crew"}, emoji_out
)
check("user mentions become names", "@Robin" in readable and "@someone" in readable,
      readable)
check("no raw snowflakes survive", "<@" not in readable, readable)
check("channels are readable", "#channel" in readable, readable)
check("custom emoji become their name", ":madness:" in readable, readable)

print("\nrole pings carry the role's real name")
check("the role name is used", "@Madness Crew" in readable, readable)
check("an unknown role falls back rather than breaking",
      "@role" in build_news.readable(
          {"content": "<@&999> hi", "mentions": []}, {"444": "Madness Crew"}, {}))
check("no roles fetched at all still reads",
      "@role" in build_news.readable({"content": "<@&444> hi", "mentions": []}))

print("\nemoji image URLs are collected alongside the text")
check("the emoji was collected", "madness" in emoji_out, str(emoji_out))
check("it points at Discord's emoji CDN",
      emoji_out.get("madness") == "https://cdn.discordapp.com/emojis/555.png",
      str(emoji_out))
animated: dict[str, str] = {}
build_news.readable({"content": "<a:spin:777>", "mentions": []}, {}, animated)
check("an animated emoji asks for the gif",
      animated.get("spin", "").endswith("/777.gif"), str(animated))
check("what the relay emits is what the launcher accepts",
      emoji_map(emoji_out) == emoji_out, str(emoji_map(emoji_out)))

print("\nan embed-only announcement is not read as empty")
embed_only = {
    "content": "",
    "embeds": [{"title": "Patch 1.2", "description": "Now with more madness."}],
}
check("the embed becomes the body",
      "Patch 1.2" in build_news.readable(embed_only), build_news.readable(embed_only))

print("\nthe relay only forwards images from Discord's own CDN")
check(
    "an attachment is taken",
    build_news.image_of(
        {
            "attachments": [
                {"content_type": "image/png",
                 "url": "https://cdn.discordapp.com/attachments/1/2/a.png"}
            ]
        }
    )
    != "",
)
check(
    "an off-CDN embed image is refused",
    build_news.image_of(
        {"embeds": [{"image": {"url": "https://evil.test/a.png"}}]}
    )
    == "",
)
check(
    "a non-image attachment is skipped",
    build_news.image_of(
        {
            "attachments": [
                {"content_type": "application/zip",
                 "url": "https://cdn.discordapp.com/attachments/1/2/a.zip"}
            ]
        }
    )
    == "",
)

print("\nvideo links are recognised in every shape people post them")
found = build_news._video_ids(
    "https://youtu.be/aaaaaaaaaaa and "
    "https://www.youtube.com/watch?v=bbbbbbbbbbb&t=30 and "
    "https://youtube.com/shorts/ccccccccccc and "
    "https://www.youtube.com/live/ddddddddddd"
)
check("all four found", len(found) == 4, str(found))
check("no duplicates from one message",
      len(build_news._video_ids("youtu.be/aaaaaaaaaaa youtu.be/aaaaaaaaaaa")) == 1)
check("a bare link to the site is not a video",
      build_news._video_ids("https://www.youtube.com/") == [])

print("\nthe YouTube feed parser reads a real Atom document")
ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>A Channel</title>
  <entry>
    <id>yt:video:aaaaaaaaaaa</id>
    <yt:videoId>aaaaaaaaaaa</yt:videoId>
    <title>First video</title>
    <author><name>A Channel</name></author>
    <published>2026-08-09T18:00:00+00:00</published>
    <media:group>
      <media:title>First video</media:title>
      <media:thumbnail url="https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"/>
    </media:group>
  </entry>
</feed>"""

original_get = build_news.get
build_news.get = lambda url, headers=None: ATOM.encode("utf-8")
try:
    uploads = build_news.youtube_uploads("UCtest")
finally:
    build_news.get = original_get

check("one upload parsed", len(uploads) == 1, str(len(uploads)))
check("title read", uploads[0]["title"] == "First video", uploads[0]["title"])
check("channel read", uploads[0]["channel"] == "A Channel", uploads[0]["channel"])
check("watch URL built", uploads[0]["url"].endswith("v=aaaaaaaaaaa"), uploads[0]["url"])
check("thumbnail is on an allowed host",
      safe_image_url(uploads[0]["thumbnail"]) != "", uploads[0]["thumbnail"])

print("\nand what it produces is what the launcher expects")
relayed = NewsFeed.from_dict(
    {"version": build_news.FEED_VERSION, "videos": uploads, "announcements": []}
)
check("the launcher reads the relay's own output", len(relayed.videos) == 1,
      str(len(relayed.videos)))
check("the title survives the round trip",
      relayed.videos[0].title == "First video", relayed.videos[0].title)

print("\nthe relay refuses to publish an empty feed when everything failed")
def _boom(*args, **kwargs):
    raise build_news.SourceError("no network")

original_messages = build_news.discord_messages
build_news.get = _boom
build_news.discord_messages = _boom
try:
    build_news.build(
        {"announcements": [{"channel_id": "1", "guild_id": "2"}]}, "token"
    )
    check("it raises rather than writing nothing", False, "no exception")
except build_news.SourceError:
    check("it raises rather than writing nothing", True)
finally:
    build_news.get = original_get
    build_news.discord_messages = original_messages


print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all news checks passed")
