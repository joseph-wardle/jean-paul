"""ShotGrid access as the Jean Paul script user"""

from dataclasses import dataclass
from typing import Any, cast

import shotgun_api3

DISCORD_ID_FIELD = "sg_discord_id"
NOTE_TYPE_FIELD = "sg_note_type"
PUBLISH_NOTE_TYPE = "Publish"
ACTIVE_STATUS = "act"

_NOTE_FIELDS = [
    "user",
    "subject",
    "note_links",
    "addressings_to",
    "addressings_cc",
    NOTE_TYPE_FIELD,
]
_DELIVERABLE_TYPES = ("Shot", "Asset")
_LOOKBACK = ["created_at", "in_last", 1, "DAY"]


@dataclass(frozen=True)
class Recipient:
    name: str
    discord_id: int | None


@dataclass(frozen=True)
class Note:
    id: int
    url: str
    author: str
    about: str
    subject: str
    is_publish: bool
    recipients: list[Recipient]


def connect(site: str, script: str, key: str) -> shotgun_api3.Shotgun:
    return shotgun_api3.Shotgun(site, script_name=script, api_key=key)


def check_schema(sg: shotgun_api3.Shotgun) -> list[str]:
    """Return a description of each field missing on the ShotGrid side."""
    problems = []
    if DISCORD_ID_FIELD not in sg.schema_field_read("HumanUser"):
        problems.append(
            f"ShotGrid People have no '{DISCORD_ID_FIELD}' field. Add a Text field named "
            "'Discord ID' under Admin → Fields → People."
        )
    if NOTE_TYPE_FIELD not in sg.schema_field_read("Note"):
        problems.append(f"ShotGrid Notes have no '{NOTE_TYPE_FIELD}' field.")
    return problems


def notes_after(sg: shotgun_api3.Shotgun, project_id: int, after: int | None) -> list[Note]:
    """The project's Notes newer than Note `after`, oldest first."""
    filters: list[Any] = [
        ["project", "is", {"type": "Project", "id": project_id}],
        ["id", "greater_than", after] if after is not None else _LOOKBACK,
    ]
    rows = _find(
        sg, "Note", filters, _NOTE_FIELDS, order=[{"field_name": "id", "direction": "asc"}]
    )
    return [_note(sg, row) for row in rows]


def _note(sg: shotgun_api3.Shotgun, row: dict[str, Any]) -> Note:
    author = row["user"] or {}
    return Note(
        id=row["id"],
        url=f"{sg.base_url.rstrip('/')}/detail/Note/{row['id']}",
        author=author.get("name") or "someone",
        about=_about(row["note_links"] or []),
        subject=row["subject"] or "",
        is_publish=row[NOTE_TYPE_FIELD] == PUBLISH_NOTE_TYPE,
        recipients=_recipients(sg, [*row["addressings_to"], *row["addressings_cc"]], author),
    )


def _recipients(
    sg: shotgun_api3.Shotgun, addressed: list[dict[str, Any]], author: dict[str, Any]
) -> list[Recipient]:
    """Every active person in To and CC, a Group as its members, once each, but the author."""
    ids = {entity["id"] for entity in addressed if entity["type"] == "HumanUser"}
    if group_ids := [entity["id"] for entity in addressed if entity["type"] == "Group"]:
        for group in _find(sg, "Group", [["id", "in", group_ids]], ["users"]):
            ids |= {user["id"] for user in group["users"] if user["type"] == "HumanUser"}
    if author.get("type") == "HumanUser":
        ids.discard(author["id"])
    if not ids:
        return []
    people = _find(
        sg,
        "HumanUser",
        [["id", "in", sorted(ids)], ["sg_status_list", "is", ACTIVE_STATUS]],
        ["name", DISCORD_ID_FIELD],
    )
    return [Recipient(person["name"], _discord_id(person[DISCORD_ID_FIELD])) for person in people]


def _about(links: list[dict[str, Any]]) -> str:
    deliverables = [link for link in links if link["type"] in _DELIVERABLE_TYPES]
    return ", ".join(link["name"] for link in deliverables or links if link.get("name"))


def _discord_id(text: str | None) -> int | None:
    text = (text or "").strip()
    return int(text) if text.isdigit() else None


def _find(
    sg: shotgun_api3.Shotgun, entity_type: str, filters: list[Any], fields: list[str], **kwargs: Any
) -> list[dict[str, Any]]:
    # The API types each row as only its type and id, whatever fields were asked for.
    return cast(list[dict[str, Any]], sg.find(entity_type, filters, fields, **kwargs))
