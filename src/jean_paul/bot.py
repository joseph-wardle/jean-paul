"""The Discord side: checks the forum setup, then keeps forum posts and issues in step."""

import asyncio
import logging
import time
from datetime import datetime

import discord
from github.Issue import Issue
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

POLL_SECONDS = 60
# The sweep re-reads both platforms: a retry net for anything a live event missed.
SWEEP_SECONDS = 15 * 60
THREAD_NAME_LIMIT = 100


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
        # One write at a time: two events for one report can't both create its other
        # half, and replies reach GitHub in Discord order.
        self._write_lock = asyncio.Lock()
        self._sync: asyncio.Task[None] | None = None
        self._sweep_due = True

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

    async def on_ready(self) -> None:
        # on_ready fires again after a fresh session, which means events were missed.
        if self._sync is not None:
            self._sweep_due = True
            return
        forum, problems = self._check_discord()
        self.setup_problems += problems
        if forum is None or self.setup_problems:
            await self.close()
            return
        # The indexes must exist before live events are handled, or a reply would
        # forward its whole thread again.
        await self._rebuild_indexes(await _forum_posts(forum))
        self.forum = forum
        self._sync = asyncio.create_task(self._keep_in_sync())
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
        open_tag, closed_tag = self._status_tags()
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
            log.info("Tagged post %s Open for issue #%d.", thread.id, number)

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

    async def reconcile_issue(self, issue: Issue) -> None:
        """Give a labelled issue its post and its thread marker, and match the post's tag
        to the issue's state."""
        async with self._write_lock:
            thread_id = next(
                (thread for thread, number in self.thread_issues.items() if number == issue.number),
                None,
            )
            if thread_id is None:
                thread = await self._create_post(issue)
            else:
                try:
                    thread = await self.fetch_channel(thread_id)
                except discord.NotFound:
                    log.warning("Issue #%d's post %s was deleted.", issue.number, thread_id)
                    return
                assert isinstance(thread, discord.Thread)

            if report.thread_id_in(issue.body) != thread.id:
                await asyncio.to_thread(github.add_thread_marker, issue, thread.id)
            await self._sync_status(thread, issue)

    async def _keep_in_sync(self) -> None:
        """Poll GitHub every minute, and sweep both platforms at start-up, after a fresh
        session and every SWEEP_SECONDS."""
        since: datetime | None = None
        next_sweep = 0.0
        while not self.is_closed():
            try:
                if self._sweep_due or time.monotonic() >= next_sweep:
                    await self._sweep_posts()
                    # The GitHub half of the sweep: every labelled issue, not just changes.
                    since = None
                    self._sweep_due = False
                    next_sweep = time.monotonic() + SWEEP_SECONDS
                since = await self._poll_issues(since)
            except Exception:
                log.exception("Syncing failed; retrying in %d s.", POLL_SECONDS)
            await asyncio.sleep(POLL_SECONDS)

    async def _sweep_posts(self) -> None:
        """Record every untagged post and forward every reply not yet on GitHub."""
        assert self.forum is not None
        posts = await _forum_posts(self.forum)
        await self._rebuild_indexes(posts)
        for thread in posts:
            try:
                await self.record_post(thread)
                if self._has_unforwarded(thread):
                    await self.forward_replies(thread)
            except Exception:
                log.exception("Could not reconcile post %s (%r).", thread.id, thread.name)

    async def _poll_issues(self, since: datetime | None) -> datetime | None:
        """Reconcile each labelled issue updated since `since`; return where to resume."""
        issues = await asyncio.to_thread(github.labelled_issues, self.repo, since)
        failed = False
        for issue in issues:
            try:
                await self.reconcile_issue(issue)
            except Exception:
                failed = True
                log.exception("Could not reconcile issue #%d.", issue.number)
        # Only advance once every issue went through, so a failure is retried.
        if failed or not issues:
            return since
        return max(issue.updated_at for issue in issues)

    async def _rebuild_indexes(self, posts: list[discord.Thread]) -> None:
        """Re-read both indexes from GitHub and the forum.

        Merged into what this run already knows, so a write GitHub hasn't listed yet
        is never forgotten and a reply is never forwarded twice.
        """
        self.thread_issues |= await asyncio.to_thread(
            github.thread_index, self.repo, self.bot_login
        )
        self.thread_issues |= await self._index_bot_posts(posts)
        forwarded = await asyncio.to_thread(
            github.newest_forwarded, self.repo, self.bot_login, self.thread_issues
        )
        for thread_id, message_id in forwarded.items():
            self.newest_forwarded[thread_id] = max(
                message_id, self.newest_forwarded.get(thread_id, 0)
            )

    async def _create_post(self, issue: Issue) -> discord.Thread:
        assert self.forum is not None
        open_tag, _ = self._status_tags()
        created = await self.forum.create_thread(
            name=issue.title[:THREAD_NAME_LIMIT],
            content=report.post_content(issue.body, issue.html_url, issue.number),
            applied_tags=[open_tag],
        )
        self.thread_issues[created.thread.id] = issue.number
        log.info("Posted issue #%d as post %s.", issue.number, created.thread.id)
        return created.thread

    async def _sync_status(self, thread: discord.Thread, issue: Issue) -> None:
        open_tag, closed_tag = self._status_tags()
        tags = thread.applied_tags
        if open_tag not in tags and closed_tag not in tags:
            # A forum post whose recording was interrupted; record_post finishes it.
            return

        is_open = issue.state == "open"
        wanted = open_tag if is_open else closed_tag
        if wanted in tags:
            if is_open and thread.archived:
                await thread.edit(archived=False)
                log.info("Un-archived open post %s for issue #%d.", thread.id, issue.number)
            return

        if thread.archived:
            thread = await thread.edit(archived=False)
        await thread.send(report.status_line(issue.state, issue.state_reason))
        others = [tag for tag in tags if tag not in (open_tag, closed_tag)]
        await thread.edit(applied_tags=[*others, wanted], archived=not is_open)
        log.info("Marked post %s %s for issue #%d.", thread.id, wanted.name, issue.number)

    async def _index_bot_posts(self, posts: list[discord.Thread]) -> dict[int, int]:
        """Map each post the bot created from an issue to that issue.

        Lets a restart find a post whose issue never got its marker.
        """
        assert self.user is not None
        index = {}
        for thread in posts:
            if thread.owner_id != self.user.id or thread.id in self.thread_issues:
                continue
            starter = await thread.fetch_message(thread.id)
            number = report.issue_number_in_post(starter.content, self.repo.html_url)
            if number is not None:
                index[thread.id] = number
        return index

    def _has_unforwarded(self, thread: discord.Thread) -> bool:
        # Saves a history request per post per sweep; unknown means look.
        newest = self.newest_forwarded.get(thread.id, thread.id)
        return thread.last_message_id is None or thread.last_message_id > newest

    async def _has_replied(self, thread: discord.Thread, issue_url: str) -> bool:
        async for message in thread.history(limit=REPLY_SEARCH_LIMIT):
            if message.author == self.user and issue_url in message.content:
                return True
        return False

    def _status_tags(self) -> tuple[discord.ForumTag, discord.ForumTag]:
        assert self.forum is not None
        return _tag(self.forum, OPEN_TAG), _tag(self.forum, CLOSED_TAG)

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


async def _forum_posts(forum: discord.ForumChannel) -> list[discord.Thread]:
    """Every post in the forum, active and archived."""
    archived = [thread async for thread in forum.archived_threads(limit=None)]
    return [*forum.threads, *archived]


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
