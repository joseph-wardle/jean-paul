"""How Discord messages are written into GitHub, and how the bot finds them again."""

import re

import discord

# Hidden in the issue body; links the issue to its forum post. A forum post's
# starter message shares its thread's id.
THREAD_MARKER = "<!-- discord-thread: {} -->"
THREAD_MARKER_PATTERN = re.compile(r"<!-- discord-thread: (\d+) -->")

# Hidden in each forwarded comment; the newest one says where forwarding resumes.
MESSAGE_MARKER = "<!-- discord-message: {} -->"
MESSAGE_MARKER_PATTERN = re.compile(r"<!-- discord-message: (\d+) -->")

# A zero-width space after "@" stops GitHub treating the word as a mention.
GITHUB_MENTION_PATTERN = re.compile(r"(?<!\w)@(?=\w)")
NO_MENTION = "@\u200b"


def thread_id_in(body: str | None) -> int | None:
    return _marked_id(THREAD_MARKER_PATTERN, body)


def message_id_in(body: str | None) -> int | None:
    return _marked_id(MESSAGE_MARKER_PATTERN, body)


def issue_body(starter: discord.Message) -> str:
    return _quote(starter, THREAD_MARKER.format(starter.channel.id))


def comment_body(message: discord.Message) -> str:
    return _quote(message, MESSAGE_MARKER.format(message.id))


def github_safe(text: str) -> str:
    """Discord text with every @mention made inert for GitHub."""
    return GITHUB_MENTION_PATTERN.sub(NO_MENTION, text)


def _quote(message: discord.Message, marker: str) -> str:
    lines = []
    if message.content:
        lines += [github_safe(message.clean_content), ""]
    author = github_safe(message.author.display_name)
    lines.append(f"Posted by **{author}** in [Discord]({message.jump_url}).")
    if message.attachments:
        names = ", ".join(f"`{attachment.filename}`" for attachment in message.attachments)
        lines.append(f"Attachments (in Discord): {names}")
    lines += ["", marker]
    return "\n".join(lines)


def _marked_id(pattern: re.Pattern[str], body: str | None) -> int | None:
    match = pattern.search(body or "")
    return int(match.group(1)) if match else None
