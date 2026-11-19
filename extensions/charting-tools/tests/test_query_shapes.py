"""Compile real querysets to SQL (no database) to check what they load.

The other tests mock the ORM, which checks the call chain but not field names
or which columns a query selects.
"""

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import Note

from charting_tools.handlers.rule_engine import NOTE_BODY_THROUGH_NOTE, _notes_query
from charting_tools.kinds import NON_TEMPLATE_KINDS, RULE
from charting_tools.models.note_template import NoteTemplate

NOTE = "a" * 32


def _sql(queryset: object) -> str:
    return str(queryset.query)  # type: ignore[attr-defined]


def test_rule_engine_notes_leave_out_the_body() -> None:
    assert "_body" in _sql(Note.objects.select_related("patient").filter(id=NOTE))  # control
    assert "_body" not in _sql(_notes_query().filter(id=NOTE))


def test_notes_reached_through_appointments_and_commands_leave_out_the_body() -> None:
    for model in (Appointment, Command):
        joined = model.objects.select_related("note", "note__patient")
        assert "_body" in _sql(joined.filter(id=NOTE))  # control
        assert "_body" not in _sql(joined.defer(*NOTE_BODY_THROUGH_NOTE).filter(id=NOTE))


def test_template_filters_are_real_fields() -> None:
    assert "kind" in _sql(NoteTemplate.objects.filter(active=True, kind=RULE))
    assert "NOT" in _sql(NoteTemplate.objects.filter(active=True).exclude(kind__in=NON_TEMPLATE_KINDS))
