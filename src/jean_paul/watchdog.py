"""Fails if any forum post has gone unrecorded: no Open or Closed tag after GRACE.

Run nightly from GitHub Actions, so a dead bot or a dead host is noticed even when
the bot can't say so itself. Reads the forum over REST; needs only the bot's token.

    DISCORD_TOKEN=... DISCORD_FORUM_ID=... jean-paul-watchdog
"""

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from jean_paul.bot import CLOSED_TAG, OPEN_TAG

API = "https://discord.com/api/v10"
# The bot records a post within seconds, or at its next sweep after an outage.
GRACE = timedelta(minutes=30)
DISCORD_EPOCH_MS = 1420070400000


def main() -> None:
    token = os.environ["DISCORD_TOKEN"]
    forum_id = os.environ["DISCORD_FORUM_ID"]

    forum = _get(token, f"/channels/{forum_id}")
    status_tags = {
        tag["id"] for tag in forum["available_tags"] if tag["name"] in (OPEN_TAG, CLOSED_TAG)
    }
    cutoff = datetime.now(UTC) - GRACE
    unrecorded = [
        post
        for post in _posts(token, forum)
        if _created(post["id"]) < cutoff and not status_tags & set(post.get("applied_tags", []))
    ]

    for post in unrecorded:
        link = f"https://discord.com/channels/{forum['guild_id']}/{post['id']}"
        print(f"Unrecorded since {_created(post['id']):%Y-%m-%d %H:%M} UTC: {post['name']} {link}")
    if unrecorded:
        print(
            f"{len(unrecorded)} post(s) never got an {OPEN_TAG} or {CLOSED_TAG} tag. Is the bot up?"
        )
        sys.exit(1)
    print(
        f"Every post in #{forum['name']} older than {GRACE // timedelta(minutes=1)} minutes is recorded."
    )


def _posts(token: str, forum: dict[str, Any]) -> list[dict[str, Any]]:
    """Every post in the forum, active and archived."""
    active = _get(token, f"/guilds/{forum['guild_id']}/threads/active")["threads"]
    posts = [thread for thread in active if thread.get("parent_id") == forum["id"]]
    before = ""
    while True:
        page = _get(token, f"/channels/{forum['id']}/threads/archived/public?limit=100{before}")
        posts += page["threads"]
        if not page["has_more"]:
            return posts
        before = f"&before={page['threads'][-1]['thread_metadata']['archive_timestamp']}"


def _created(snowflake: str) -> datetime:
    return datetime.fromtimestamp(((int(snowflake) >> 22) + DISCORD_EPOCH_MS) / 1000, UTC)


def _get(token: str, path: str) -> Any:
    request = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "DiscordBot (https://github.com/joseph-wardle/jean-paul, 0.1)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


if __name__ == "__main__":
    main()
