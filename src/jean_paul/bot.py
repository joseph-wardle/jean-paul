"""The Discord side: checks the forum setup, then copies forum posts and replies to GitHub."""

import asyncio
import logging

import discord
from github.Repository import Repository

from jean_paul import github, report
from jean_paul.config import Config

log = logging.getLogger(__name__)

# Only Manage Threads members may apply these, so a tag is proof the bot set it.
OPEN_TAG = "Open"
CLOSED_TAG = "Closed"

FORUM_PERMISSIONS = (
    "view_channel",
    "read_message_history",
    "send_messages",
    "send_messages_in_threads",
    "manage_threads",
)
MAINTAINER_PERMISSIONS = ("view_channel", "send_messages")

# System messages (pins, renames) are not part of the conversation.
FORWARDED_TYPES = (discord.MessageType.default, discord.MessageType.reply)

# How far back to look for an earlier "Recorded as" reply after an interrupted run.
REPLY_SEARCH_LIMIT = 50


class SetupError(Exception):
    pass


class JeanPaul(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.config = config
        self.setup_problems: list[str] = []
        self.forum: discord.ForumChannel | None = None
        self.thread_issues: dict[int, int] = {}
        self.newest_forwarded: dict[int, int] = {}
        # One write at a time: two events for one post can't both create an issue,
        # and replies reach GitHub in Discord order.
        self._write_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        # PyGithub is synchronous; keep it off the event loop.
        self.repo: Repository
        self.repo, self.bot_login = await asyncio.to_thread(
            github.connect,
            self.config.github_app_id,
            self.config.github_private_key,
            self.config.github_repo,
        )
        self.setup_problems += await asyncio.to_thread(github.check_repo, self.repo)
        self.thread_issues = await asyncio.to_thread(github.thread_index, self.repo, self.bot_login)
        self.newest_forwarded = await asyncio.to_thread(
            github.newest_forwarded, self.repo, self.bot_login, self.thread_issues
        )

    async def on_ready(self) -> None:
        # on_ready fires again after a fresh session; the setup only needs checking once.
        if self.forum is not None:
            return
        forum, problems = self._check_discord()
        self.setup_problems += problems
        if self.setup_problems:
            await self.close()
            return
        self.forum = forum
        log.info("Connected as %s; filing reports on %s.", self.user, self.repo.full_name)

    async def on_message(self, message: discord.Message) -> None:
        thread = message.channel
        if not isinstance(thread, discord.Thread):
            return
        if self.forum is None or thread.parent_id != self.forum.id:
            return
        if message.author == self.user:
            return
        try:
            # A new post is recorded when its starter message arrives, not on thread
            # create: with an attachment, the thread exists seconds before its message.
            if message.id == thread.id:
                await self.record_post(thread, message)
            else:
                await self.forward_replies(thread)
        except Exception:
            log.exception("Could not copy message %s in %r to GitHub.", message.id, thread.name)

    async def record_post(
        self, thread: discord.Thread, starter: discord.Message | None = None
    ) -> None:
        """Give a forum post its issue, its "Recorded as" reply and its Open tag.

        Each step checks for the one before it, so an interrupted run can be repeated.
        """
        assert self.forum is not None
        open_tag = _tag(self.forum, OPEN_TAG)
        closed_tag = _tag(self.forum, CLOSED_TAG)
        async with self._write_lock:
            if open_tag in thread.applied_tags or closed_tag in thread.applied_tags:
                return

            number = self.thread_issues.get(thread.id)
            if number is None:
                if starter is None:
                    starter = await thread.fetch_message(thread.id)
                issue = await asyncio.to_thread(
                    github.create_report_issue,
                    self.repo,
                    thread.name,
                    report.issue_body(starter),
                )
                number = issue.number
                self.thread_issues[thread.id] = number
                log.info("Recorded post %s as issue #%d.", thread.id, number)

            issue_url = f"{self.repo.html_url}/issues/{number}"
            if not await self._has_replied(thread, issue_url):
                await thread.send(f"Recorded as [#{number}](<{issue_url}>).")
            await thread.add_tags(open_tag)

    async def forward_replies(self, thread: discord.Thread) -> None:
        """Comment every reply newer than the last one forwarded, oldest first.

        Stops at the first failure, so the next try resumes without skipping or
        reordering anything.
        """
        async with self._write_lock:
            number = self.thread_issues.get(thread.id)
            if number is None:
                log.warning("Post %s has no issue yet; its replies wait.", thread.id)
                return
            # The starter message shares the thread's id, so replies come after it.
            after = discord.Object(self.newest_forwarded.get(thread.id, thread.id))
            async for message in thread.history(limit=None, after=after, oldest_first=True):
                if message.author != self.user and message.type in FORWARDED_TYPES:
                    await asyncio.to_thread(
                        github.add_comment, self.repo, number, report.comment_body(message)
                    )
                    log.info("Forwarded message %s to issue #%d.", message.id, number)
                self.newest_forwarded[thread.id] = message.id

    async def _has_replied(self, thread: discord.Thread, issue_url: str) -> bool:
        async for message in thread.history(limit=REPLY_SEARCH_LIMIT):
            if message.author == self.user and issue_url in message.content:
                return True
        return False

    def _check_discord(self) -> tuple[discord.ForumChannel | None, list[str]]:
        guild = self.get_guild(self.config.guild_id)
        if guild is None:
            return None, [f"The bot is not in server {self.config.guild_id}. Invite it first."]

        forum = guild.get_channel(self.config.forum_id)
        if not isinstance(forum, discord.ForumChannel):
            return None, [f"Channel {self.config.forum_id} is missing or is not a forum."]

        maintainer = guild.get_channel(self.config.maintainer_channel_id)
        if not isinstance(maintainer, discord.TextChannel):
            return None, [
                f"Channel {self.config.maintainer_channel_id} is missing or is not a text channel."
            ]

        return forum, (
            _check_tags(forum)
            + _check_permissions(forum, guild.me, FORUM_PERMISSIONS)
            + _check_permissions(maintainer, guild.me, MAINTAINER_PERMISSIONS)
        )


def run(config: Config) -> None:
    client = JeanPaul(config)
    client.run(config.discord_token, log_handler=None)
    if client.setup_problems:
        raise SetupError("\n".join(client.setup_problems))


def _tag(forum: discord.ForumChannel, name: str) -> discord.ForumTag:
    # The start-up check guarantees both tags exist.
    return next(tag for tag in forum.available_tags if tag.name == name)


def _check_tags(forum: discord.ForumChannel) -> list[str]:
    problems = []
    tags = {tag.name: tag for tag in forum.available_tags}
    for name in (OPEN_TAG, CLOSED_TAG):
        tag = tags.get(name)
        if tag is None:
            problems.append(
                f"#{forum.name} has no '{name}' tag. Add it in the forum's Tags settings."
            )
        elif not tag.moderated:
            problems.append(
                f"#{forum.name}'s '{name}' tag can be applied by anyone. "
                "Turn on 'Only allow moderators to apply this tag'."
            )
    return problems


def _check_permissions(
    channel: discord.abc.GuildChannel, member: discord.Member, required: tuple[str, ...]
) -> list[str]:
    granted = channel.permissions_for(member)
    missing = [name for name in required if not getattr(granted, name)]
    if not missing:
        return []
    return [f"The bot lacks {', '.join(missing)} in #{channel.name}."]
