"""Keeping the waitlist buttons in step with the roster.

Both buttons decide their label when they render, from whether the patient has a
live entry. Nothing redraws them on its own, so after a write from the roster they
would keep offering "Add to waitlist" for someone already on the list until the
page was reloaded.

There are two surfaces and the SDK has a separate effect for each: the chart
header is addressed by patient, a note header by note. Emitting only the first is
why the chart used to update immediately while a note stayed stale until reload.

Paired with ``services/banner.py``: together they leave a patient's chart telling
the truth after a write anywhere. The banner carries the status, these refresh the
actions.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.action_button import (
    ReloadNoteActionButtonsEffect,
    ReloadPatientActionButtonsEffect,
)
from canvas_sdk.v1.data import Appointment
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteStates

# Mirrors handlers/appointment_button.py: the button only appears on an
# appointment whose slot was given up, and either record can say so.
FREED_STATUSES = (
    str(AppointmentProgressStatus.CANCELLED),
    str(AppointmentProgressStatus.NOSHOWED),
)
FREED_NOTE_STATES = (str(NoteStates.CANCELLED), str(NoteStates.NOSHOW))

# A patient with a long cancellation history would otherwise turn one waitlist
# write into an unbounded pile of reload effects.
MAX_NOTE_RELOADS = 10


def reload_chart_buttons(entry: Any) -> list[Effect]:
    """Ask the chart header, and any affected note header, to redraw.

    Returns nothing for an entry with no resolvable patient, matching
    ``banner_effects``: an effect keyed on ``None`` addresses no chart.
    """
    patient = getattr(entry, "patient", None)
    patient_id = getattr(patient, "id", None)
    if not patient_id:
        return []

    effects: list[Effect] = [
        ReloadPatientActionButtonsEffect(id=str(patient_id)).apply()
    ]
    effects.extend(_note_reloads(entry, patient))
    return effects


def _note_reloads(entry: Any, patient: Any) -> list[Effect]:
    """Redraw the note buttons whose label this write could have changed.

    Narrowed to the entry's own service. The note button asks "is this patient
    already waiting for *this slot's* service", so a change to their Follow-up
    entry cannot alter the label on a cancelled Physical -- reloading those would
    be work with no visible effect.
    """
    note_type_dbid = getattr(entry, "note_type_id", None)
    patient_dbid = getattr(patient, "dbid", None)
    if note_type_dbid is None or patient_dbid is None:
        # An "any service" entry has no single service to narrow by, and every
        # freed note's label could change. Left alone rather than reloading a
        # patient's whole cancellation history on one write.
        return []

    notes = (
        Appointment.objects.filter(
            patient_id=patient_dbid,
            note_type_id=note_type_dbid,
            entered_in_error__isnull=True,
        )
        .select_related("note__current_state")
        .order_by("-start_time")[:MAX_NOTE_RELOADS]
    )

    effects: list[Effect] = []
    for appointment in notes:
        if not _is_freed(appointment):
            continue
        note_id = getattr(getattr(appointment, "note", None), "id", None)
        if note_id:
            effects.append(ReloadNoteActionButtonsEffect(id=note_id).apply())
    return effects


def _is_freed(appointment: Any) -> bool:
    """Whether this appointment's slot was given up, by either record."""
    if str(getattr(appointment, "status", "") or "") in FREED_STATUSES:
        return True
    current = getattr(getattr(appointment, "note", None), "current_state", None)
    return str(getattr(current, "state", "") or "") in FREED_NOTE_STATES
