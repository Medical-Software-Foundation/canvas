"""The entry points. Each criterion below names opening one of these as its When clause."""

import datetime
import json

from medication_followup_protocol.applications.program_admin import ProgramAdmin
from medication_followup_protocol.handlers.appointment_watcher import AppointmentWatcher
from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton
from tests.conftest import make_event


def payload(effect):
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


# --- The chart application is gone, and so are its two tests
#
# ProgramPanel put an icon in the chart's application row which opened the read only programs
# view in the right chart pane. The practice asked for it to be removed and for the note footer
# button to open the enrolment form in that pane instead, so the icon and the view it opened
# went together, they were one manifest entry.
#
# The two tests that stood here asserted that opening that application targeted the right chart
# pane, for AC15 and AC16. There is nothing left to open, so they are removed rather than
# rewritten against a surface that no longer exists. Both criteria still say a staff member
# opens the panel on the patient's chart and neither has a door any more, which is a trace break
# that goes back through superproduct-analyze and is not something a test here can settle.
# AC15's data is still covered, by the enrollments endpoint tests in tests/api.


def test_the_configuration_page_opens_as_a_full_page():
    """Covers criterion: AC1."""
    event = make_event("APPLICATION__ON_OPEN", context={})

    opened = payload(ProgramAdmin(event).on_open())

    # A full page, because the configuration needs no patient open.
    assert opened["target"] == "page"


def test_the_note_header_control_opens_the_enrolment_form_beside_the_note():
    """Covers scenario: AC30, the enrolment form opens in the right chart pane rather than a modal. Covers criterion: AC4. Covers criterion: AC30.

    The right chart pane rather than a modal. A modal covered the note the provider reads to
    decide what to enrol the patient on, and a button on a note opening the right pane is the
    pairing the design system names as standard for exactly that reason. The ordinary pane
    rather than the large one, because the content did not fill the large one.
    """
    event = make_event(
        "ACTION_BUTTON_CLICKED",
        context={"key": EnrollmentButton.BUTTON_KEY, "note_id": "note-42"},
    )

    effects = EnrollmentButton(event).compute()

    opened = payload(effects[0])
    assert opened["target"] == "right_chart_pane"
    assert "note-42" in opened["url"]


def test_the_control_sits_in_the_note_header():
    """Covers criterion: AC4.

    The header rather than the footer. The feedback of 2026-08-25 asked for the control to
    move there and to show only when the patient qualifies, and the two go together, since
    a control in the header alongside the note's own title is only tolerable when it is
    absent for the notes it has nothing to offer.
    """
    assert EnrollmentButton.BUTTON_LOCATION == EnrollmentButton.ButtonLocation.NOTE_HEADER


def test_booking_a_recheck_records_it_against_the_enrolment(enrolment, patient):
    """Covers criterion: AC8."""
    from canvas_sdk.test_utils.factories import NoteTypeFactory
    from canvas_sdk.v1.data import Appointment

    note_type = NoteTypeFactory(id=enrolment.recheck_note_type_id)
    appointment = Appointment.objects.create(
        patient=patient,
        note_type=note_type,
        start_time=datetime.datetime(2026, 9, 1, 9, 0, tzinfo=datetime.timezone.utc),
        status="confirmed",
        duration_minutes=20,
        telehealth_instructions_sent=False,
        meeting_link="",
    )

    event = make_event("APPOINTMENT_CREATED", target=str(appointment.id))
    assert AppointmentWatcher(event).compute() == []

    enrolment.refresh_from_db()
    assert enrolment.recheck_booked_appointment_id == str(appointment.id)


def test_cancelling_the_recheck_clears_it_again(enrolment, patient):
    """Covers criterion: AC9."""
    from canvas_sdk.test_utils.factories import NoteTypeFactory
    from canvas_sdk.v1.data import Appointment

    note_type = NoteTypeFactory(id=enrolment.recheck_note_type_id)
    appointment = Appointment.objects.create(
        patient=patient,
        note_type=note_type,
        start_time=datetime.datetime(2026, 9, 1, 9, 0, tzinfo=datetime.timezone.utc),
        status="confirmed",
        duration_minutes=20,
        telehealth_instructions_sent=False,
        meeting_link="",
    )
    booked = make_event("APPOINTMENT_CREATED", target=str(appointment.id))
    AppointmentWatcher(booked).compute()

    appointment.status = "cancelled"
    appointment.save()
    cancelled = make_event("APPOINTMENT_CANCELED", target=str(appointment.id))
    AppointmentWatcher(cancelled).compute()

    enrolment.refresh_from_db()
    assert enrolment.recheck_booked_appointment_id is None
