"""How a report is written on each platform, and how the bot finds its other half."""

import re

import discord

# Hidden in the issue body; links the issue to its forum post.
_THREAD_MARKER = "<!-- discord-thread: {} -->"
_THREAD_MARKER_PATTERN = re.compile(r"<!-- discord-thread: (\d+) -->")

# Hidden in each forwarded comment; the newest one says where forwarding resumes.
_MESSAGE_MARKER = "<!-- discord-message: {} -->"
_MESSAGE_MARKER_PATTERN = re.compile(r"<!-- discord-message: (\d+) -->")

# Starts each comment mirrored from GitHub; its link says which comment it was.
_COMMENT_HEAD = "**{login}** on [GitHub](<{url}>):"
_COMMENT_HEAD_PATTERN = re.compile(r"\*\*[\w\[\]-]+\*\* on \[GitHub\]\(<\S+#issuecomment-(\d+)>\):")

# Files pasted into an issue or comment on GitHub.
GITHUB_FILE_PATTERN = re.compile(
    r"https://github\.com/user-attachments/(?:assets|files)/[^\s)\"'<>]+"
)
# GitHub writes a pasted image as an <img> tag, which Discord would show as raw HTML.
IMG_TAG_PATTERN = re.compile(r"<img\b[^>]*?\bsrc=\"([^\"]+)\"[^>]*>")

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


# Each attachment, with its link on GitHub, or None where it couldn't be copied.
Copied = list[tuple[discord.Attachment, str | None]]


def issue_body(starter: discord.Message, copied: Copied) -> str:
    return _quote(starter, copied, _THREAD_MARKER.format(starter.channel.id))


def comment_body(message: discord.Message, copied: Copied) -> str:
    return _quote(message, copied, _MESSAGE_MARKER.format(message.id))


def attachment_path(message: discord.Message, attachment: discord.Attachment) -> str:
    return f"{message.channel.id}/{message.id}/{attachment.filename}"


def comment_message(login: str, url: str, body: str | None) -> str:
    """A GitHub comment as a Discord message, cut to fit."""
    head = _COMMENT_HEAD.format(login=login, url=url)
    return f"{head}\n{_fit(discord_text(body), DISCORD_MESSAGE_LIMIT - len(head) - 1)}"


def comment_id_in(content: str) -> int | None:
    """The GitHub comment a bot message mirrors, if it mirrors one."""
    match = _COMMENT_HEAD_PATTERN.match(content)
    return int(match.group(1)) if match else None


def github_files(body: str | None) -> list[str]:
    """Every file pasted into a GitHub text, once each, in order."""
    return list(dict.fromkeys(GITHUB_FILE_PATTERN.findall(body or "")))


def discord_text(body: str | None) -> str:
    text = HTML_COMMENT_PATTERN.sub("", body or "")
    return IMG_TAG_PATTERN.sub(r"<\1>", text).strip()


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
    text = _fit(discord_text(body), DISCORD_MESSAGE_LIMIT - len(link) - 2)
    return f"{text}\n\n{link}" if text else link


def status_line(state: str, state_reason: str | None) -> str:
    if state == "open":
        return REOPENED_LINE
    return CLOSED_LINES.get(state_reason or "", CLOSED_LINE)


def github_safe(text: str) -> str:
    """Discord text with every @mention made inert for GitHub."""
    return GITHUB_MENTION_PATTERN.sub(NO_MENTION, text)


def _quote(message: discord.Message, copied: Copied, marker: str) -> str:
    lines = []
    if message.content:
        lines += [github_safe(message.clean_content), ""]
    if copied:
        lines += [_attachment_line(attachment, link) for attachment, link in copied]
        lines.append("")
    author = github_safe(message.author.display_name)
    lines.append(f"Posted by **{author}** in [Discord]({message.jump_url}).")
    lines += ["", marker]
    return "\n".join(lines)


def _attachment_line(attachment: discord.Attachment, link: str | None) -> str:
    name = attachment.filename
    if link is None:
        return f"`{name}` (in Discord)"
    if (attachment.content_type or "").startswith("image/"):
        return f"![{name}]({link})"
    return f"[{name}]({link})"


def _fit(text: str, room: int) -> str:
    return text if len(text) <= room else text[: room - 1] + "…"


def _marked_id(pattern: re.Pattern[str], body: str | None) -> int | None:
    match = pattern.search(body or "")
    return int(match.group(1)) if match else None
