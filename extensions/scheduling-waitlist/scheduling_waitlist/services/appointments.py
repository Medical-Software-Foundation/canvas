"""What each waiting patient already has booked.

A waitlist goes stale quietly. Somebody is added, gets seen a fortnight later
through a route nobody recorded, and their row keeps claiming they are waiting --
so schedulers stop trusting the list and start ringing people who no longer need
the call.

``handlers/appointment_booked.py`` closes an entry when a booking *satisfies* what
it asked for, and that strictness is deliberate: a patient waiting for Dr Chen who
gets booked with somebody else still wants Dr Chen. The cost is exactly the
staleness above, because the entry stays open with no sign that anything happened.
This module supplies that sign. It reports, it never closes -- a person glancing at
a flagged row makes a better decision than the matcher can.

One query per roster page, not one per row. See :func:`next_appointment_map`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from canvas_sdk.v1.data import Appointment
from canvas_sdk.v1.data.appointment import AppointmentProgressStatus

from scheduling_waitlist.constants import RECENT_VISIT_WINDOW_DAYS
from scheduling_waitlist.services.display import note_type_name, staff_name
from scheduling_waitlist.services.options import is_patient_visit

# A given-up slot is not an appointment the patient has. Named from the enum so a
# renamed member breaks the import rather than silently matching nothing.
GIVEN_UP_STATUSES = (
    str(AppointmentProgressStatus.CANCELLED),
    str(AppointmentProgressStatus.NOSHOWED),
)

# Someone who arrived was seen, whatever the note says afterwards. Checked rather
# than assuming a past appointment was attended: an appointment still sitting at
# "unconfirmed" a week after its start time tells us nothing about whether the
# patient turned up.
ATTENDED_STATUSES = frozenset(
    {
        str(AppointmentProgressStatus.ARRIVED),
        str(AppointmentProgressStatus.ROOMED),
        str(AppointmentProgressStatus.EXITED),
    }
)

# What the row is telling the reader.
STATE_UPCOMING = "upcoming"
STATE_ATTENDED = "attended"

# Read for the two names the column shows. Without these the column would cost
# two queries per row, which is the whole reason the map is built in one pass.
APPOINTMENT_RELATIONS = ("note_type", "provider")


def describe(appointment: Any, *, state: str) -> dict[str, Any]:
    """One appointment as the roster renders it.

    The time goes out as an ISO string and is formatted in the browser, matching
    every other date on the roster: the page is read by a person sitting in a
    practice, and their own clock is the one they are comparing against.

    An appointment with no provider reports an empty string rather than
    ``staff_name``'s placeholder. The roster joins these two fields with a
    separator and drops the blanks, so "Unnamed staff member" would be a
    fabricated detail in a column whose whole job is to be glanceable.
    """
    start = getattr(appointment, "start_time", None)
    provider = getattr(appointment, "provider", None)
    return {
        "start": start.isoformat() if isinstance(start, datetime) else "",
        "type": note_type_name(getattr(appointment, "note_type", None)),
        "provider": staff_name(provider) if provider is not None else "",
        "state": state,
    }


def _relevant(rows: list[Any], *, now: datetime) -> dict[str, Any] | None:
    """The one appointment worth showing for a patient, from theirs in order.

    Precedence is the reader's, not the clock's. An upcoming visit answers "does
    this person still need a call?" outright, so it wins even when a recent visit
    would also be worth flagging. Only when there is nothing ahead of them does a
    visit they have already attended become the interesting fact.
    """
    for row in rows:
        start = _start(row)
        # Inclusive: a visit starting this minute has not been attended, and
        # calling it "seen" would flag the row wrongly.
        if start is not None and start >= now:
            return describe(row, state=STATE_UPCOMING)

    attended = [
        row
        for row in rows
        if str(getattr(row, "status", "") or "") in ATTENDED_STATUSES
    ]
    if attended:
        # Rows arrive oldest first, so the last one is the most recent visit.
        return describe(attended[-1], state=STATE_ATTENDED)

    return None


def _start(appointment: Any) -> datetime | None:
    value = getattr(appointment, "start_time", None)
    return value if isinstance(value, datetime) else None


def next_appointment_map(
    patient_dbids: list[Any], *, now: datetime
) -> dict[Any, dict[str, Any]]:
    """For each patient given, the appointment their roster row should show.

    Keyed by patient dbid, and patients with nothing to show are simply absent.

    One query for the whole page. Both halves of the question -- what is coming up
    and what has recently happened -- are answered from a single window that
    starts ``RECENT_VISIT_WINDOW_DAYS`` in the past, so the alternative of two
    queries buys nothing. Cancelled and no-showed appointments are excluded in
    SQL; the non-visit note types go in Python, against the same
    ``is_patient_visit`` the appointment-type dropdown uses, because a calendar
    block on a patient's chart is not an appointment they are attending.
    """
    unique_dbids = {dbid for dbid in patient_dbids if dbid is not None}
    if not unique_dbids:
        return {}

    rows = (
        Appointment.objects.filter(
            patient_id__in=list(unique_dbids),
            entered_in_error__isnull=True,
            start_time__gte=now - timedelta(days=RECENT_VISIT_WINDOW_DAYS),
        )
        .exclude(status__in=list(GIVEN_UP_STATUSES))
        .select_related(*APPOINTMENT_RELATIONS)
        .order_by("start_time")
    )

    by_patient: dict[Any, list[Any]] = {}
    for row in rows:
        if not is_patient_visit(getattr(row, "note_type", None)):
            continue
        by_patient.setdefault(getattr(row, "patient_id", None), []).append(row)

    described: dict[Any, dict[str, Any]] = {}
    for patient_dbid, appointments in by_patient.items():
        if patient_dbid is None:
            continue
        relevant = _relevant(appointments, now=now)
        if relevant is not None:
            described[patient_dbid] = relevant
    return described
