"""Swaps a visit note's template when its visit type changes.

A booked note gets the template for the appointment's note type
(``insertion.auto_apply``), and each command it inserts is tagged with
``TEMPLATE_COMMAND_KEY``. When the visit type later changes (a reschedule to a
different type, or the type edited on the appointment), the note is brought in
line with the new type's template:

- Commands both templates have stay as they are. Two commands are the same when
  they are the same command type and, for questionnaire-type commands, use the
  same questionnaire (by code).
- The old template's other commands are removed, but only while they are
  uncommitted and unchanged since they were inserted. Anything edited, by a
  person or another plugin, stays.
- The new template's other commands are added, tagged the same way.

Commands a person added themselves are never tagged, so they are never touched.
Notes whose template went in before commands were tagged are left alone, since
there is no telling which of their commands came from the template.
"""

from collections import Counter
from datetime import timedelta
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note import Note as NoteEffect
from canvas_sdk.v1.data.command import Command, CommandMetadata
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteMetadata
from canvas_sdk.v1.data.questionnaire import Questionnaire
from logger import log

from charting_tools.command_catalog import CATALOG
from charting_tools.insertion import (
    APPLIED_METADATA_KEY,
    NO_TEMPLATE,
    TEMPLATE_COMMAND_KEY,
    build_commands,
    originate_effects,
)
from charting_tools.kinds import NON_TEMPLATE_KINDS
from charting_tools.models.note_template import NoteTemplate
from charting_tools.note_states import OPEN_NOTE_STATES
from charting_tools.note_types import template_for_note_type
from charting_tools.questionnaires import needs_questionnaire


# A command saved within this long of being inserted counts as unchanged:
# inserting with pre-filled data can save it more than once.
UNCHANGED_TOLERANCE = timedelta(seconds=5)

# Note states a template can still be swapped in.
SWAPPABLE_STATES = OPEN_NOTE_STATES

Signature = tuple[str, str, str]


def entry_signature(entry: dict[str, Any]) -> Signature:
    """What makes a template entry the same command as another."""
    schema_key = entry.get("schema_key", "")
    if not needs_questionnaire(schema_key):
        return (schema_key, "", "")
    ref = entry.get("questionnaire") or {}
    return (schema_key, ref.get("code_system", ""), ref.get("code", ""))


def row_signatures(rows: list[Any]) -> dict[Any, Signature]:
    """Each command row's signature, reading questionnaire codes in one query."""
    dbids = {
        _as_int(((row.data or {}).get("questionnaire") or {}).get("value"))
        for row in rows
        if needs_questionnaire(row.schema_key)
    }
    dbids.discard(None)
    codes = {
        dbid: (system, code)
        for dbid, system, code in Questionnaire.objects.filter(dbid__in=dbids).values_list(
            "dbid", "code_system", "code"
        )
    } if dbids else {}
    out: dict[Any, Signature] = {}
    for row in rows:
        if not needs_questionnaire(row.schema_key):
            out[row.dbid] = (row.schema_key, "", "")
            continue
        dbid = _as_int(((row.data or {}).get("questionnaire") or {}).get("value"))
        system, code = codes.get(dbid, ("", "")) if dbid is not None else ("", "")
        out[row.dbid] = (row.schema_key, system, code)
    return out


def unchanged(row: Any) -> bool:
    """Whether a command is still uncommitted and as it was inserted."""
    if row.state != "staged" or row.committer_id is not None:
        return False
    if row.created is None or row.modified is None:
        return False
    return bool(row.modified - row.created <= UNCHANGED_TOLERANCE)


def switch_template(note: Note, note_type_identifier: str, secrets: dict[str, Any]) -> list[Effect]:
    """Bring a note whose template was applied automatically in line with a new visit type."""
    marker = NoteMetadata.objects.filter(note_id=note.dbid, key=APPLIED_METADATA_KEY).first()
    if marker is None:
        return []
    # Only note templates carry note types (a NULL kind is a template saved before kinds).
    templates = NoteTemplate.objects.filter(active=True).exclude(kind__in=NON_TEMPLATE_KINDS).order_by("name")
    template = template_for_note_type(templates, note_type_identifier)
    wanted = template.template_id if template is not None else NO_TEMPLATE
    if marker.value == wanted:
        return []

    state = CurrentNoteStateEvent.objects.filter(note_id=note.dbid).values_list("state", flat=True).first()
    if state not in SWAPPABLE_STATES:
        log.info(f"Note {note.id} is {state}; leaving its template as is")
        return []
    # A note booked with no template has nothing to swap out; one templated
    # before commands were tagged can't tell its template's commands apart.
    if marker.value != NO_TEMPLATE and not CommandMetadata.objects.filter(
        command__note_id=note.dbid, key=TEMPLATE_COMMAND_KEY
    ).exists():
        log.info(f"Note {note.id} has no tagged template commands; leaving its template as is")
        return []

    rows = list(
        Command.objects.filter(
            note_id=note.dbid,
            entered_in_error__isnull=True,
            metadata__key=TEMPLATE_COMMAND_KEY,
        )
        .exclude(state="entered_in_error")
        .order_by("dbid")
    )
    signatures = row_signatures(rows)
    entries = [e for e in (template.commands or []) if e.get("schema_key") in CATALOG] if template else []
    needed = Counter(entry_signature(e) for e in entries)

    # Edited and committed commands claim the shared places first, so an
    # unchanged duplicate is the one removed.
    remove = []
    for row in sorted(rows, key=lambda r: (unchanged(r), r.dbid)):
        signature = signatures[row.dbid]
        if needed[signature] > 0:
            needed[signature] = needed[signature] - 1
        elif unchanged(row) and row.schema_key in CATALOG:
            remove.append(row)

    to_add = []
    for entry in entries:
        signature = entry_signature(entry)
        if needed[signature] > 0:
            needed[signature] = needed[signature] - 1
            to_add.append(entry)

    effects: list[Effect] = [
        CATALOG[row.schema_key].command_class(command_uuid=str(row.id)).delete() for row in remove
    ]
    if template is not None and to_add:
        built = build_commands(_Entries(template, to_add), note)
        effects.extend(originate_effects(built, secrets, replace_line=False, template_tag=template.template_id))
    log.info(
        f"Note {note.id} visit type changed: template {marker.value} -> {wanted}, "
        f"removed {len(remove)}, added {len(to_add)}, kept {len(rows) - len(remove)}"
    )
    effects.append(NoteEffect(instance_id=str(note.id)).upsert_metadata(key=APPLIED_METADATA_KEY, value=wanted))
    return effects


class _Entries:
    """Some of a template's entries, shaped like the template so they build the same way."""

    def __init__(self, template: Any, commands: list[dict[str, Any]]) -> None:
        self.template_id = template.template_id
        self.kind = template.kind
        self.commands = commands


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
