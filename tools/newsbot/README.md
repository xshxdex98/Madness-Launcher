# News relay

The launcher's News tab reads one file: a JSON feed of Discord announcements
and video uploads. This directory builds that file.

## Why a relay at all

Discord has no public way to read a channel's messages. Reading one needs a bot
token, and **a token shipped inside the launcher is a token every user can
extract from the executable** and use to act as your bot. The token therefore
never leaves the machine that runs this script. Users only ever fetch the
resulting `news.json`, which contains nothing secret.

YouTube is included here for a different reason: its per-channel RSS feed needs
no key at all and the launcher *could* read it directly, but folding it in means
the launcher makes one request instead of one per channel, and channel uploads
and links shared in Discord arrive already merged and de-duplicated.

## Setup

**1. Create the bot**

- <https://discord.com/developers/applications> → New Application → Bot.
- Copy the token. This is the only secret in the whole system.
- Under Bot → Privileged Gateway Intents, enable **Message Content Intent**.
  Without it Discord returns messages with an empty `content` field and every
  announcement comes through blank.

**2. Invite it to your server**

Under OAuth2 → URL Generator, tick scope `bot` and permissions **View
Channels** and **Read Message History**. Nothing else — the bot never posts.
Open the generated URL and add it to the server.

**3. Collect the IDs**

Turn on Discord's Developer Mode (User Settings → Advanced), then right-click
the server icon and each channel and choose Copy ID.

For YouTube you need the canonical `UC…` channel ID, which a `@handle` URL does
not show:

```
python build_news.py --resolve https://www.youtube.com/@yourchannel
```

**4. Write the config**

```
cp sources.example.json sources.json
```

Fill in `announcements` (the channel the launcher shows as news),
`video_channels` (channels to scan for YouTube links people post), and
`youtube` (channels whose uploads should appear). Any of the three can be left
as an empty list.

**5. Try it locally**

```
DISCORD_BOT_TOKEN=... python build_news.py --dry-run
```

On Windows PowerShell:

```
$env:DISCORD_BOT_TOKEN = "..."
python build_news.py --dry-run
```

**6. Put it on a schedule**

Add the token as a repository secret named `DISCORD_BOT_TOKEN`
(Settings → Secrets and variables → Actions), commit `sources.json`, and the
workflow at `.github/workflows/news.yml` takes it from there — every 15
minutes, committing `news.json` only when it has actually changed.

`sources.json` holds no secrets, only channel IDs, so it is safe to commit. If
your repository is private you will need Pages or another host for step 7
instead of a raw URL.

**7. Point the launcher at it**

The feed's URL is the raw file:

```
https://raw.githubusercontent.com/<owner>/<repo>/main/news.json
```

Paste that into the launcher under **Settings → News**. To ship it as the
default for everyone, set `DEFAULT_NEWS_URL` in `madness_launcher/config.py`
instead — the Settings field then only exists for people who want to override
it.

## Timing

Two caches sit between a Discord post and a user seeing it:

| Stage | Delay |
| --- | --- |
| GitHub Actions cron | up to ~15 min, and late under load |
| `raw.githubusercontent.com` CDN | ~5 min |
| Launcher's own throttle | 5 min, bypassed by the Refresh button |

So worst case is roughly 25 minutes. If that matters, run the script somewhere
that can serve it on request instead — the launcher does not care what is at
the other end of the URL, only that it answers with this JSON.

## Feed format

Version 1. The launcher ignores fields it does not know and skips entries it
cannot read, so adding a field is safe; changing what an existing one means is
not, and should bump `version`.

```json
{
  "version": 1,
  "generated": "2026-08-10T12:00:00Z",
  "announcements": [
    {
      "id": "1234567890",
      "author": "Someone",
      "avatar": "https://cdn.discordapp.com/avatars/…",
      "posted": "2026-08-10T11:40:00Z",
      "body": "Plain text. **Bold**, *italic* and `code` are rendered.",
      "url": "https://discord.com/channels/…",
      "image": "https://cdn.discordapp.com/attachments/…"
    }
  ],
  "videos": [
    {
      "id": "dQw4w9WgXcQ",
      "title": "A video",
      "channel": "A channel",
      "published": "2026-08-09T18:00:00Z",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
      "source": "youtube"
    }
  ]
}
```

`source` is `youtube` for a channel upload or `discord` for a link someone
shared, which the launcher labels on the card.

Images are only fetched from `i.ytimg.com`, `img.youtube.com`,
`cdn.discordapp.com` and `media.discordapp.net`. A thumbnail pointing anywhere
else is dropped by the launcher rather than requested — see `IMAGE_HOSTS` in
`madness_launcher/news/model.py`. Whoever can write to the feed can otherwise
make every launcher in the wild call out to a host of their choosing.
