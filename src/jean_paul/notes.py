import asyncio
import logging

import discord
import shotgun_api3
from discord.utils import escape_markdown

from jean_paul import shotgrid

log = logging.getLogger(__name__)

DM_SEARCH_LIMIT = 50

_UNDELIVERABLE = (400, 403, 404)


class NoteDelivery:
    def __init__(self, client: discord.Client, sg: shotgun_api3.Shotgun, project_id: int) -> None:
        self.client = client
        self.sg = sg
        self.project_id = project_id
        # The newest Note whose recipients were all told; None looks back a day.
        self._newest: int | None = None

    async def deliver(self) -> None:
        """DM the recipients of every Note since the last delivery."""
        notes = await asyncio.to_thread(
            shotgrid.notes_after, self.sg, self.project_id, self._newest
        )
        for note in notes:
            for person in note.recipients:
                await self._tell(note, person)
            self._newest = note.id

    async def _tell(self, note: shotgrid.Note, person: shotgrid.Recipient) -> None:
        if person.discord_id is None:
            # No note id, so the maintainer hears once per person, not once per note.
            log.warning(
                "%s has no Discord ID in ShotGrid, so Jean Paul can't DM them about their "
                "notes. Fill it in on their People page.",
                person.name,
            )
            return
        try:
            channel = await self.client.create_dm(discord.Object(person.discord_id))
            if not await self._already_told(channel, note):
                await channel.send(message(note))
                log.info("Told %s of note %d.", person.name, note.id)
        except discord.HTTPException as error:
            if error.status not in _UNDELIVERABLE:
                raise
            log.warning(
                "Could not DM %s (Discord ID %d in ShotGrid): %s. Check the ID on their "
                "People page, and that they are in the server and accept DMs from it.",
                person.name,
                person.discord_id,
                error.text,
            )

    async def _already_told(self, channel: discord.DMChannel, note: shotgrid.Note) -> bool:
        return any(
            [
                note.url in sent.content
                async for sent in channel.history(limit=DM_SEARCH_LIMIT)
                if sent.author == self.client.user
            ]
        )


def message(note: shotgrid.Note) -> str:
    link = f"[Open it in ShotGrid](<{note.url}>)"
    author = escape_markdown(note.author)
    if note.is_publish:
        return f"{escape_markdown(note.subject)} by {author}. There's a note for you. {link}"
    about = f" on {escape_markdown(note.about)}" if note.about else ""
    return f"You have a new note{about} from {author}. {link}"
