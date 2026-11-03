"""Attaches the quickpick and order-set panel to Assess and Diagnose commands.

The panel is custom HTML on the staged command (``set_custom_html``). It is
written once per command, since rewriting it on every edit makes it flash, and
written again on PRE_COMMIT with a fresh token: Canvas keeps showing a
command's custom HTML after commit but won't change it then, so that last write
is the one the committed command keeps. The panel itself hides once the note is
no longer open.
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
from logger import log

from charting_tools.panel import (
    build_panel_html,
    charted_code_cache_key,
    find_icd10,
    panel_kinds,
    panel_written_cache_key,
)
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

        kinds = panel_kinds()
        html = build_panel_html(base_url, sign_token(note_uuid, command_uuid, key, TOKEN_TTL_SECONDS), kinds)
        cache.set(panel_written_cache_key(command_uuid), "1", timeout_seconds=PANEL_REFRESH_SECONDS)
        return [self.COMMAND_CLASS(command_uuid=command_uuid).set_custom_html(html)]

    def _note_uuid(self, context: dict[str, Any], command_uuid: str) -> str:
        # The command isn't saved yet at POST_ORIGINATE, so prefer the event context.
        note = context.get("note")
        if isinstance(note, dict) and (note.get("uuid") or note.get("id")):
            return str(note.get("uuid") or note.get("id"))
        note_id = Command.objects.filter(id=command_uuid).values_list("note__id", flat=True).first()
        return str(note_id) if note_id else ""


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
