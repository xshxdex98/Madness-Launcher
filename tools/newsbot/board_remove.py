"""Remove a record from the community board.

The board is rebuilt from the board channel on every relay run, so a record is
removed by deleting the message that carries it. The next run simply does not
see it and, if somebody else had a time on that race, they move up.

A webhook can delete the messages it created, which is every record the
launcher has ever posted, so no bot token is needed here.

    python board_remove.py 1536468121873817611
    python board_remove.py 1536468121873817611 1536470000000000000

Message IDs come from Discord: turn on Developer Mode (User Settings →
Advanced), right-click a message, Copy Message ID. They also appear as
`message_id` against every record in news.json, so a disputed entry on the
board can be traced back to the message that made the claim.

The webhook URL is read from sources.json, the same one the launcher posts to.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "MadnessLauncherBoardTool/1.0"


def webhook_url() -> str:
    config = Path(__file__).with_name("sources.json")
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"Could not read {config}: {exc}")
    url = str(data.get("records_webhook") or "").strip()
    if not url:
        sys.exit("records_webhook is not set in sources.json.")
    return url


def remove(url: str, message_id: str) -> bool:
    """Delete one message. True if it is gone, whether or not we deleted it."""
    request = urllib.request.Request(
        f"{url}/messages/{message_id}",
        method="DELETE",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status in (200, 204)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # Already deleted, or posted by something other than this webhook.
            print(f"  {message_id}: not found (already gone?)")
            return True
        if exc.code == 429:
            print(f"  {message_id}: rate limited — wait a moment and retry")
        else:
            print(f"  {message_id}: Discord answered {exc.code}")
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  {message_id}: {exc}")
        return False


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 1
    url = webhook_url()
    ok = 0
    for message_id in argv:
        cleaned = message_id.strip()
        if not cleaned.isdigit():
            print(f"  {cleaned!r}: not a message ID")
            continue
        if remove(url, cleaned):
            ok += 1
            print(f"  {cleaned}: removed")
    print(
        f"\n{ok} of {len(argv)} removed. The board catches up on the next relay "
        "run, or run the workflow now to see it immediately."
    )
    return 0 if ok == len(argv) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
