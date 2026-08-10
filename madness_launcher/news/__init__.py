"""The news feed: Discord announcements and video uploads.

Neither source can be read from the launcher directly. Discord has no public
API for a channel's messages — reading one needs a bot token, and a token
shipped inside the executable is a token anyone who downloads the launcher can
extract and use. So the launcher reads neither: a relay does that server-side
and publishes a single plain JSON file, which is all this package fetches. See
tools/newsbot/README.md for the relay.
"""

from .images import ThumbnailCache
from .model import (
    FEED_VERSION,
    Announcement,
    NewsFeed,
    Video,
    age_of,
    safe_image_url,
    safe_url,
)
from .service import NewsService

__all__ = [
    "Announcement",
    "FEED_VERSION",
    "NewsFeed",
    "NewsService",
    "ThumbnailCache",
    "Video",
    "age_of",
    "safe_image_url",
    "safe_url",
]
