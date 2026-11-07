"""How a report is written on each platform, and how the bot finds its other half."""

import re

import discord

# Hidden in the issue body; links the issue to its forum post.
_THREAD_MARKER = "<!-- discord-thread: {} -->"
_THREAD_MARKER_PATTERN = re.compile(r"<!-- discord-thread: (\d+) -->")

# Hidden in each forwarded comment; the newest one says where forwarding resumes.
_MESSAGE_MARKER = "<!-- discord-message: {} -->"
_MESSAGE_MARKER_PATTERN = re.compile(r"<!-- discord-message: (\d+) -->")

# A zero-width space after "@" stops GitHub treating the word as a mention.
GITHUB_MENTION_PATTERN = re.compile(r"(?<!\w)@(?=\w)")
NO_MENTION = "@\u200b"

DISCORD_MESSAGE_LIMIT = 2000
THREAD_NAME_LIMIT = 100
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)

CLOSED_LINES = {
    "completed": "Closed on GitHub as done.",
    "not_planned": "Closed on GitHub as not planned.",
    "duplicate": "Closed on GitHub as a duplicate.",
}
CLOSED_LINE = "Closed on GitHub."
REOPENED_LINE = "Reopened on GitHub."


def thread_id_in(body: str | None) -> int | None:
    return _marked_id(_THREAD_MARKER_PATTERN, body)


def message_id_in(body: str | None) -> int | None:
    return _marked_id(_MESSAGE_MARKER_PATTERN, body)


def issue_body(starter: discord.Message) -> str:
    return _quote(starter, _THREAD_MARKER.format(starter.channel.id))


def comment_body(message: discord.Message) -> str:
    return _quote(message, _MESSAGE_MARKER.format(message.id))


def recorded_line(number: int, issue_url: str) -> str:
    return f"Recorded as [#{number}](<{issue_url}>)."


def issue_number_in_post(content: str, repo_url: str) -> int | None:
    """The issue a bot-created post links to, from its starter message."""
    match = re.search(rf"{re.escape(repo_url)}/issues/(\d+)", content)
    return int(match.group(1)) if match else None


def post_title(issue_title: str) -> str:
    return issue_title[:THREAD_NAME_LIMIT]


def post_content(body: str | None, issue_url: str, number: int) -> str:
    """An issue body as a forum post's starter message, cut to fit with a link to the rest."""
    link = f"[#{number} on GitHub](<{issue_url}>)"
    text = HTML_COMMENT_PATTERN.sub("", body or "").strip()
    room = DISCORD_MESSAGE_LIMIT - len(link) - 2
    if len(text) > room:
        text = text[: room - 1] + "…"
    return f"{text}\n\n{link}" if text else link


def status_line(state: str, state_reason: str | None) -> str:
    if state == "open":
        return REOPENED_LINE
    return CLOSED_LINES.get(state_reason or "", CLOSED_LINE)


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
