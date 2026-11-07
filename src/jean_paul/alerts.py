"""Warnings and errors the bot survives, posted to the private maintainer channel."""

import asyncio
import logging
import time
import traceback

import discord

from jean_paul.report import DISCORD_MESSAGE_LIMIT

# A failure that keeps happening (GitHub down, a deleted post) is repeated this often,
# not on every retry.
REPEAT_SECONDS = 6 * 60 * 60


class ChannelAlerts(logging.Handler):
    def __init__(self, channel: discord.TextChannel) -> None:
        super().__init__(logging.WARNING)
        self.channel = channel
        self._last_sent: dict[str, float] = {}
        # The event loop keeps only weak references to tasks.
        self._sending: set[asyncio.Task[None]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            # The last line says what went wrong; the full traceback stays in the log.
            reason = traceback.format_exception_only(record.exc_info[1])[-1].strip()
            text += f"\n```\n{reason[:1500]}\n```"

        now = time.monotonic()
        if now - self._last_sent.get(text, -REPEAT_SECONDS) < REPEAT_SECONDS:
            return
        self._last_sent[text] = now

        task = asyncio.get_running_loop().create_task(self._send(text, record))
        self._sending.add(task)
        task.add_done_callback(self._sending.discard)

    async def _send(self, text: str, record: logging.LogRecord) -> None:
        try:
            await self.channel.send(text[:DISCORD_MESSAGE_LIMIT])
        except discord.HTTPException:
            # Not logged through this handler, or a dead channel would alert about itself.
            self.handleError(record)
