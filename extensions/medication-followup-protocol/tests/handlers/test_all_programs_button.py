"""The all programs control in the patient header, and the pane it opens.

This control is what replaced the chart panel application the practice asked to have
removed. It carries no eligibility of its own, it only asks whether the patient already
has a program running, which is why a patient on nothing sees no control rather than one
opening onto an empty pane.
"""

import datetime
import json

from tests.conftest import make_event


def payload(effect):
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


def show_event(patient_id):
    """The event the platform fires when it renders a patient header."""
    return make_event("SHOW_CHART_PATIENT_HEADER_BUTTON", target=str(patient_id), context={})


def test_the_control_shows_for_a_patient_with_a_running_program(enrolment, patient):
    """Covers scenario: AC25, the Follow ups control shows for an active enrolment or an eligible unenrolled prescription and hides for neither. Covers criterion: AC25."""
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    assert AllProgramsButton(show_event(patient.id)).visible() is True


def test_the_control_stays_hidden_for_a_patient_with_none(patient):
    """Covers scenario: AC25, the Follow ups control shows for an active enrolment or an eligible unenrolled prescription and hides for neither. Covers criterion: AC25.

    No control at all rather than one opening onto an empty pane, which is what removes
    the empty state as something anybody has to design.
    """
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    assert AllProgramsButton(show_event(patient.id)).visible() is False


def test_a_stopped_program_does_not_keep_the_control_showing(enrolment, patient):
    """Covers scenario: AC16, a patient with no enrolment and no eligible prescription shows no banner and no Follow ups control. Covers criterion: AC16.

    Only an active enrolment counts. A patient whose only program was stopped is back to
    having nothing running, and the chart says nothing about them again.
    """
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton
    from medication_followup_protocol.models import EnrollmentStatus

    enrolment.status = EnrollmentStatus.STOPPED
    enrolment.save()

    assert AllProgramsButton(show_event(patient.id)).visible() is False


def test_the_control_emits_nothing_when_it_is_not_visible(patient):
    """Covers criterion: AC16.

    compute() on the base class is what turns visible() into no button at all, so this
    asserts the outcome the platform actually sees rather than only the predicate.
    """
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    assert AllProgramsButton(show_event(patient.id)).compute() == []


def test_the_control_is_emitted_when_it_is_visible(enrolment, patient):
    """Covers scenario: AC15, the Follow ups control opens the Ongoing tab showing every program a patient is on. Covers criterion: AC15."""
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    effects = AllProgramsButton(show_event(patient.id)).compute()

    assert len(effects) == 1


def test_the_control_sits_in_the_patient_header(enrolment, patient):
    """Covers criterion: AC25.

    The patient header rather than the applications row, which is the location the
    practice asked to have cleared and the reason this is a new control rather than the
    old one restored.
    """
    from canvas_sdk.handlers.action_button import ActionButton
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    assert AllProgramsButton.BUTTON_LOCATION == ActionButton.ButtonLocation.CHART_PATIENT_HEADER


def test_clicking_opens_the_pane_in_the_right_chart_pane(enrolment, patient):
    """Covers scenario: AC26, clicking the Follow ups control opens the patient scoped pane. Covers criterion: AC26."""
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    event = make_event(
        "ACTION_BUTTON_CLICKED",
        target=str(patient.id),
        context={"key": AllProgramsButton.BUTTON_KEY},
    )

    opened = payload(AllProgramsButton(event).compute()[0])

    assert opened["target"] == "right_chart_pane"


def test_the_pane_it_opens_is_scoped_to_that_patient(enrolment, patient):
    """Covers scenario: AC26, clicking the Follow ups control opens the patient scoped pane. Covers criterion: AC26.

    The patient arrives as the click event's own target, since the chart carries no note
    to read one off, and the url has to carry it or the pane would not know whose
    programs to render.
    """
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton

    event = make_event(
        "ACTION_BUTTON_CLICKED",
        target=str(patient.id),
        context={"key": AllProgramsButton.BUTTON_KEY},
    )

    opened = payload(AllProgramsButton(event).compute()[0])

    assert str(patient.id) in opened["url"]
    assert "/panel" in opened["url"]


def test_a_second_running_program_still_shows_one_control(
    enrolment, medication_class, patient, staff
):
    """Covers criterion: AC15.

    The control is per patient rather than per program, unlike the banner, so two
    programs still put one control in the header and the pane lists both.
    """
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton
    from medication_followup_protocol.models import Enrollment

    Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label="warfarin",
        sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 8, 20),
        recheck_note_type_id=medication_class.recheck_note_type_id,
    )

    assert len(AllProgramsButton(show_event(patient.id)).compute()) == 1


def test_the_control_shows_for_an_eligible_prescription_with_no_enrolment_ever(
    medication_class, patient, staff
):
    """Covers scenario: AC40, the Follow ups control shows for an eligible prescription even with no enrolment ever. Covers criterion: AC40."""
    from unittest.mock import MagicMock, patch

    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from medication_followup_protocol.handlers.all_programs_button import AllProgramsButton
    from medication_followup_protocol.models import CoverageKind, MedicationClassCoverage
    from medication_followup_protocol.services import eligibility
    from tests.conftest import make

    path = [2549, 3050, 24, 3064]
    MedicationClassCoverage.objects.create(
        medication_class=medication_class, kind=CoverageKind.GROUP,
        etc_path_id=path, etc_path_name=["a", "b", "c", "d"],
        display_name="lisinopril 10 mg tablet",
    )
    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    make(
        MedicationCoding, medication=medication, display="lisinopril 20 mg tablet",
        system="http://www.fdbhealth.com/", code="fdb-lisinopril-20",
    )
    PrescriptionFactory(
        patient=patient, prescriber=staff, medication=medication, note=note,
        committer=CanvasUserFactory(),
    )

    response = MagicMock()
    response.json.return_value = {"etc_path_id": path}
    with patch.object(eligibility.ontologies_http, "get_json", return_value=response):
        visible = AllProgramsButton(show_event(patient.id)).visible()

    assert visible is True
