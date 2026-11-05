"""How a Discord post is written into GitHub, and how the bot finds it again."""

import re

import discord

# Hidden in the issue body; links the issue to its forum post. A forum post's
# starter message shares its thread's id.
THREAD_MARKER = "<!-- discord-thread: {} -->"
THREAD_MARKER_PATTERN = re.compile(r"<!-- discord-thread: (\d+) -->")

# A zero-width space after "@" stops GitHub treating the word as a mention.
GITHUB_MENTION_PATTERN = re.compile(r"(?<!\w)@(?=\w)")
NO_MENTION = "@\u200b"


def thread_id_in(body: str | None) -> int | None:
    match = THREAD_MARKER_PATTERN.search(body or "")
    return int(match.group(1)) if match else None


def issue_body(starter: discord.Message) -> str:
    lines = []
    if starter.content:
        lines += [github_safe(starter.clean_content), ""]
    lines.append(
        f"Posted by **{github_safe(starter.author.display_name)}** in [Discord]({starter.jump_url})."
    )
    if starter.attachments:
        names = ", ".join(f"`{attachment.filename}`" for attachment in starter.attachments)
        lines.append(f"Attachments (in Discord): {names}")
    lines += ["", THREAD_MARKER.format(starter.channel.id)]
    return "\n".join(lines)


def github_safe(text: str) -> str:
    """Discord text with every @mention made inert for GitHub."""
    return GITHUB_MENTION_PATTERN.sub(NO_MENTION, text)
