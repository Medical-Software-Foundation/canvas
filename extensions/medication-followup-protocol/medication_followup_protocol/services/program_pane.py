"""The section component shared by the note scoped pane and the patient scoped pane.

Both panes show the same shape for one enrolment, its status, what it is called, its
steps with their due dates and statuses, and a link back to the note it started from.
The note scoped pane shows one section per class the note's own prescriptions matched,
and the patient scoped pane shows one section per program the patient is on, and both
call this module rather than building that shape for themselves, so a change to what a
section carries is one file rather than two that drift apart. This module knows
nothing about either caller, only about one enrolment at a time and the batch of them a
caller hands it.
"""

from __future__ import annotations

import datetime
from typing import Any, Sequence

from canvas_sdk.v1.data import Note

from medication_followup_protocol.models.enrollment import EnrolledStep, Enrollment
from medication_followup_protocol.models.program import StepKind
from medication_followup_protocol.services.practice_time import today


def _step_summary(step: EnrolledStep) -> str:
    """What a step does, in the words the practice wrote, read live off the class.

    Read live rather than copied at enrolment, which is what lets an edit to a step's
    wording on the medication class reach a patient already running on it.
    """
    program_step = step.program_step
    if step.kind == StepKind.TASK:
        return program_step.task_title
    if step.kind == StepKind.QUESTIONNAIRE:
        return program_step.message_body or "Questionnaire to the patient"
    return program_step.message_body


def _step_row(step: EnrolledStep, as_of: datetime.date) -> dict[str, Any]:
    """One row of a section's step table, its own timing, its wording and its outcome."""
    return {
        "day_offset": step.day_offset,
        "kind": step.kind,
        "condition": step.condition or "",
        "summary": _step_summary(step),
        "due_date": step.due_date.isoformat(),
        "days_until_due": (step.due_date - as_of).days,
        "status": step.status,
        "failure_reason": step.failure_reason,
    }


def _note_link(enrollment: Enrollment) -> str | None:
    """The chart permalink back to the note this enrolment started from.

    None when the enrolment carries no start_note_dbid, which is true for a program
    started before that field existed, so no link is rendered rather than one that
    leads nowhere. Where a link exists it carries the note's own database id as a
    noteId query parameter on the patient's own chart address rather than as a hash,
    the same mechanism the chart's own note permalink already relies on to scroll a
    note into view in place.
    """
    if not enrollment.start_note_dbid:
        return None
    return f"/patient/{enrollment.patient.id}?noteId={enrollment.start_note_dbid}"


#: What a starting note contributes to a section, the same two facts _note_payload in
#: api/program_api.py hands back as "at" and "provider_name", kept as one pair so a
#: missing note reads as the same absence on both.
_NoteFacts = tuple[str | None, str]


def _note_starting_facts(enrollments: Sequence[Enrollment]) -> dict[int, _NoteFacts]:
    """The starting moment and the provider's name, for every note these enrolments cite.

    Computed from note.datetime_of_service and note.provider, the same two fields
    _note_payload in api/program_api.py reads for its own "at" and "provider_name" keys,
    so the patient scoped pane and the note scoped pane describe one note in one sentence
    rather than in two paraphrases of it. Read in one query over every enrolment's
    start_note_dbid rather than one query per enrolment, the same batching rule the steps
    query above already follows.
    """
    note_dbids = {e.start_note_dbid for e in enrollments if e.start_note_dbid}
    if not note_dbids:
        return {}

    facts: dict[int, _NoteFacts] = {}
    for note in Note.objects.filter(dbid__in=list(note_dbids)).select_related("provider"):
        moment = note.datetime_of_service
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        provider = note.provider
        facts[note.dbid] = (
            moment.isoformat(),
            f"{provider.first_name} {provider.last_name}" if provider else "",
        )
    return facts


def _section(
    enrollment: Enrollment,
    steps: Sequence[EnrolledStep],
    note_facts: dict[int, _NoteFacts],
) -> dict[str, Any]:
    """One enrolment's section, its steps already handed in rather than queried here.

    The steps come from the caller rather than from a query against this enrolment
    alone, because a pane showing several enrolments has to batch that query itself to
    avoid firing one query per section, and a shared component that batched only for
    the caller with a single enrolment would be the wrong shape for the caller with
    several. note_facts is the same kind of batch, one lookup for the starting note's
    own moment and provider rather than a query per section.
    """
    ordered = sorted(steps, key=lambda step: (step.day_offset, step.sequence))
    at, provider_name = (
        note_facts.get(enrollment.start_note_dbid, (None, ""))
        if enrollment.start_note_dbid
        else (None, "")
    )
    return {
        "id": enrollment.dbid,
        "medication_class": enrollment.medication_class.name,
        "medication_label": enrollment.medication_label,
        "status": enrollment.status,
        "start_date": enrollment.start_date.isoformat(),
        "stopped_reason": enrollment.stopped_reason,
        "note_link": _note_link(enrollment),
        # The same note the link points at, handed over as its own value rather than left
        # to be parsed back out of the link. A pane that wants to drive the chart in place
        # needs the id on its own, and reading it back off the url with a pattern means the
        # link's shape and the pane's regex have to agree forever, with nothing failing
        # loudly when they stop agreeing.
        "start_note_dbid": enrollment.start_note_dbid or None,
        # The moment and the provider the note scoped pane already reads off the same note,
        # here so the patient scoped pane can recognise it on the chart the same way, an
        # instant and a name rather than a guess built from anything this section itself
        # renders.
        "start_note_at": at,
        "start_note_provider_name": provider_name,
        "steps": [_step_row(step, today()) for step in ordered],
    }


def render_sections(enrollments: Sequence[Enrollment]) -> list[dict[str, Any]]:
    """Every one of these enrolments as its own section, in one batch.

    Both panes render more than one enrolment at a time, the note scoped pane one
    section per class the note's prescriptions matched and the patient scoped pane one
    section per program the patient is on, so every enrolment's steps are read here in
    one query rather than one query per section, the same batching program_walker.py
    already relies on for the same reason. The starting note's own moment and provider
    are batched the same way, in _note_starting_facts, rather than read once per section.
    """
    if not enrollments:
        return []

    steps_by_enrollment: dict[int, list[EnrolledStep]] = {}
    for step in (
        EnrolledStep.objects.filter(enrollment__dbid__in=[e.dbid for e in enrollments])
        .select_related("program_step")
        .order_by("day_offset", "sequence")
    ):
        steps_by_enrollment.setdefault(step.enrollment_id, []).append(step)

    note_facts = _note_starting_facts(enrollments)

    return [
        _section(enrollment, steps_by_enrollment.get(enrollment.dbid, []), note_facts)
        for enrollment in enrollments
    ]
