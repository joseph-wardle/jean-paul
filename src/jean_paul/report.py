"""How a report is written on each platform, and how the bot finds its other half."""

import re
from typing import NamedTuple

import discord
from discord.utils import escape_markdown

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

STATUS_LINES = {
    "completed": (
        "Splendid. This has been seen to{fix}.",
        "Consider the matter handled{fix}.",
        "Right as rain{fix}. This calls for some marmelade!",
        "Sorted{fix}. Father would have been proud.",
    ),
    "not_planned": (
        "After some deliberation in the drawing room, we shan't be pursuing this one. My sincere apologies.",
        "Not to be, I'm afraid. The estate's attentions lie elsewhere for now.",
        "Set aside for the present. Do raise it again should circumstances change.",
        "Perhaps another time. For the moment we have more pressing matters to attend to."
    ),
    "duplicate": (
        "Ah, we've been over this one before. It's being looked after in another report.",
        "This matter is already in hand elsewhere, I'm pleased to say.",
        "I daresay I've seen this one before already. I think it's being taken care of."
    ),
    "closed": ("This one has been closed. Good day.",),
    "reopened": (
        "Back again, I see. This one's been reopened.",
        "On reflection, this matter is open once more.",
        "Reopened. One mustn't let these things linger.",
    ),
}

RECORDED_LINES = (
    "Duly noted. I've had this entered into the ledger as {issue}.",
    "I've passed this along to the estate's engineer as {issue}.",
    "Thank you for bringing this to out attention. It's on file as {issue}.",
    "Noted, and filed away as {issue}.",
    "I shall see that this is looked into. It's recorded as {issue}.",
    "Ah, a new matter. I've written it up as {issue}.",
    "Hmm, interesting. I'll send word right away. I've recorded it as {issue} for now.",
)

CLOSING_GIFS: tuple[str, ...] = ()


class Closer(NamedTuple):
    """The pull request or commit that closed an issue."""

    label: str
    title: str
    url: str


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
    line = RECORDED_LINES[number % len(RECORDED_LINES)]
    return line.format(issue=f"[#{number}](<{issue_url}>)")


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


def status_line(
    state: str, state_reason: str | None, number: int, closer: Closer | None = None
) -> str:
    if state == "open":
        kind = "reopened"
    else:
        kind = state_reason if state_reason in STATUS_LINES else "closed"
    lines = STATUS_LINES[kind]
    fix = ""
    if closer is not None:
        fix = f" in [{closer.label}](<{closer.url}>), *{escape_markdown(closer.title)}*"
    return lines[number % len(lines)].format(fix=fix)


def closing_gif(state_reason: str | None, number: int) -> discord.Embed | None:
    if state_reason != "completed" or not CLOSING_GIFS:
        return None
    return discord.Embed().set_image(url=CLOSING_GIFS[number % len(CLOSING_GIFS)])


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
