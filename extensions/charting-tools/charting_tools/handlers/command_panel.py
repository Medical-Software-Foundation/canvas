"""Attaches the quickpick and order-set panel to Assess and Diagnose commands.

The panel is custom HTML on the staged command (``set_custom_html``). It is
written once per command, since rewriting it on every edit makes it flash, and
written again on PRE_COMMIT with a fresh token: Canvas keeps showing a
command's custom HTML after commit but won't change it then, so that last write
is the one the committed command keeps. The panel itself hides once the note is
no longer open.
Opening a note writes the panel again, with a fresh token, on each of its staged
Assess and Diagnose commands. Otherwise a command nobody edits keeps its first
token, which expires after TOKEN_TTL_SECONDS even across page reloads.
It always carries the quick-add buttons, plus a tab for quickpicks and for order
sets when there are any.
Every event also stores the ICD-10 being charted, so the panel can float the
quickpicks and order sets made for it and use it as their orders' indication.
"""

from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands import AssessCommand, DiagnoseCommand
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note
from logger import log

from charting_tools.panel import (
    build_panel_html,
    charted_code_cache_key,
    find_icd10,
    panel_kinds,
    panel_written_cache_key,
)
from charting_tools.note_states import note_is_open
from charting_tools.settings import instance_url, panel_signing_key
from charting_tools.tokens import sign_token

# Longer than a command stays open for charting.
CACHE_TTL_SECONDS = 43200

# The panel's token lasts TOKEN_TTL_SECONDS. The panel is written again (with a
# fresh token) on the first edit after PANEL_REFRESH_SECONDS, so a command being
# worked on keeps a working panel.
TOKEN_TTL_SECONDS = 14400
PANEL_REFRESH_SECONDS = 10800


class _PanelHandler(BaseHandler):
    """Shared logic; subclasses name the command and its events."""

    COMMAND_CLASS: Any = None
    COMMIT_EVENT: int = 0

    def compute(self) -> list[Effect]:
        """Store the charted code; attach the panel once; re-sign it just before commit."""
        command_uuid = str(self.event.target.id or "")
        if not command_uuid:
            return []
        committing = self.event.type == self.COMMIT_EVENT

        context = self.event.context if isinstance(self.event.context, dict) else {}
        cache = get_cache()
        code = find_icd10(context.get("fields"))
        if code:
            cache.set(charted_code_cache_key(command_uuid), code, timeout_seconds=CACHE_TTL_SECONDS)

        if cache.get(panel_written_cache_key(command_uuid)) and not committing:
            return []

        key = panel_signing_key(self.secrets)
        base_url = instance_url(self.secrets)
        if not key or not base_url:
            log.warning(
                "PANEL_TOKEN_SIGNING_KEY or CANVAS_INSTANCE_URL is not set; not attaching the panel"
            )
            return []

        note_uuid = self._note_uuid(context, command_uuid)
        if not note_uuid:
            log.warning(f"No note found for command {command_uuid}; not attaching the panel")
            return []

        return [panel_effect(self.COMMAND_CLASS, note_uuid, command_uuid, key, base_url, panel_kinds())]

    def _note_uuid(self, context: dict[str, Any], command_uuid: str) -> str:
        # The command isn't saved yet at POST_ORIGINATE, so prefer the event context.
        note = context.get("note")
        if isinstance(note, dict) and (note.get("uuid") or note.get("id")):
            return str(note.get("uuid") or note.get("id"))
        note_id = Command.objects.filter(id=command_uuid).values_list("note__id", flat=True).first()
        return str(note_id) if note_id else ""


def panel_effect(command_class: Any, note_uuid: str, command_uuid: str, key: str, base_url: str,
                 kinds: list[str]) -> Effect:
    """Write the panel on a command, with a fresh token."""
    html = build_panel_html(base_url, sign_token(note_uuid, command_uuid, key, TOKEN_TTL_SECONDS), kinds)
    get_cache().set(panel_written_cache_key(command_uuid), "1", timeout_seconds=PANEL_REFRESH_SECONDS)
    return command_class(command_uuid=command_uuid).set_custom_html(html)


# The commands that carry the panel, by schema key.
PANEL_COMMANDS = {"assess": AssessCommand, "diagnose": DiagnoseCommand}


class NoteOpenedPanels(BaseHandler):
    """Re-signs the panel on a note's staged Assess and Diagnose commands when the note is opened."""

    RESPONDS_TO = [EventType.Name(EventType.NOTE_OPENED)]

    def compute(self) -> list[Effect]:
        """One panel write per staged Assess or Diagnose on an open note."""
        context = self.event.context if isinstance(self.event.context, dict) else {}
        note_uuid = str((context.get("note") or {}).get("id") or "")
        key = panel_signing_key(self.secrets)
        base_url = instance_url(self.secrets)
        if not note_uuid or not key or not base_url:
            return []
        note_dbid = Note.objects.filter(id=note_uuid).values_list("dbid", flat=True).first()
        if note_dbid is None or not note_is_open(note_dbid):
            return []
        # Canvas won't change a committed command's custom HTML, so only staged ones.
        commands = list(
            Command.objects.filter(
                note_id=note_dbid,
                schema_key__in=list(PANEL_COMMANDS),
                state="staged",
                committer__isnull=True,
                entered_in_error__isnull=True,
            )
            .order_by("dbid")
            .values_list("id", "schema_key")
        )
        if not commands:
            return []
        kinds = panel_kinds()
        return [
            panel_effect(PANEL_COMMANDS[schema_key], note_uuid, str(command_id), key, base_url, kinds)
            for command_id, schema_key in commands
        ]


class AssessPanel(_PanelHandler):
    """The panel on an Assess command."""

    RESPONDS_TO = [
        EventType.Name(EventType.ASSESS_COMMAND__POST_ORIGINATE),
        EventType.Name(EventType.ASSESS_COMMAND__CONDITION_SELECTED),
        EventType.Name(EventType.ASSESS_COMMAND__POST_UPDATE),
        EventType.Name(EventType.ASSESS_COMMAND__PRE_COMMIT),
    ]
    COMMAND_CLASS = AssessCommand
    COMMIT_EVENT = EventType.ASSESS_COMMAND__PRE_COMMIT


class DiagnosePanel(_PanelHandler):
    """The panel on a Diagnose command."""

    RESPONDS_TO = [
        EventType.Name(EventType.DIAGNOSE_COMMAND__POST_ORIGINATE),
        EventType.Name(EventType.DIAGNOSE_COMMAND__POST_UPDATE),
        EventType.Name(EventType.DIAGNOSE_COMMAND__PRE_COMMIT),
    ]
    COMMAND_CLASS = DiagnoseCommand
    COMMIT_EVENT = EventType.DIAGNOSE_COMMAND__PRE_COMMIT
