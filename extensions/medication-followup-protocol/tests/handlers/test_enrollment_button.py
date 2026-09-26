"""The note header control, its eligibility gate, and the pane it opens.

The matching rule itself is covered against services/eligibility.py. What is covered here
is the handler's own half, that it reads the note off the show event's context, hands that
to the matching rule rather than repeating it, and emits no control at all when the answer
is no. Those are different failures. A correct matching rule behind a gate that never asks
it still shows the control on every note in the practice.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make, make_event

#: Lisinopril, as the local catalogue carries it, both strengths sharing this path.
ACE_PATH = [2549, 3050, 24, 3064]


def payload(effect):
    """The data an effect carries."""
    return json.loads(effect.payload)["data"]


def show_event(note_dbid=None):
    """The event the platform fires when it renders a note header."""
    context = {} if note_dbid is None else {"note_id": note_dbid}
    return make_event("SHOW_NOTE_HEADER_BUTTON", context=context)


@pytest.fixture
def note_with_matching_prescription(patient, staff, medication_class):
    """A note carrying a committed prescription a configured class covers."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding

    from medication_followup_protocol.models import CoverageKind, MedicationClassCoverage

    MedicationClassCoverage.objects.create(
        medication_class=medication_class,
        kind=CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["Cardiovascular Agents", "ACE Inhibitors", "Lisinopril", "Lisinopril"],
        display_name="lisinopril 10 mg tablet",
    )
    note = NoteFactory(patient=patient)
    medication = MedicationFactory(patient=patient)
    make(
        MedicationCoding,
        medication=medication,
        display="lisinopril 20 mg tablet",
        system="http://www.fdbhealth.com/",
        code="fdb-lisinopril-20",
    )
    PrescriptionFactory(
        patient=patient,
        prescriber=staff,
        medication=medication,
        note=note,
        committer=CanvasUserFactory(),
    )
    return note


def _catalogue_answers(path):
    """Patch the ontologies lookup the matching rule makes."""
    from medication_followup_protocol.services import eligibility

    response = MagicMock()
    response.json.return_value = {"etc_path_id": path}
    return patch.object(eligibility.ontologies_http, "get_json", return_value=response)


def test_the_control_shows_once_a_prescription_matches(note_with_matching_prescription):
    """Covers scenario: AC20, the enrolment control shows once a prescription matches a class's coverage. Covers criterion: AC20."""
    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    with _catalogue_answers(ACE_PATH):
        visible = EnrollmentButton(show_event(note_with_matching_prescription.dbid)).visible()

    assert visible is True


def test_the_control_is_emitted_when_it_matches(note_with_matching_prescription):
    """Covers scenario: AC20, the enrolment control shows once a prescription matches a class's coverage. Covers criterion: AC20.

    The predicate and the emitted button are different claims, and the platform only ever
    sees the second one.
    """
    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    with _catalogue_answers(ACE_PATH):
        effects = EnrollmentButton(show_event(note_with_matching_prescription.dbid)).compute()

    assert len(effects) == 1


def test_the_control_stays_hidden_when_nothing_matches(patient, staff, medication_class):
    """Covers scenario: AC21, the enrolment control stays hidden when no prescription matches. Covers criterion: AC21.

    A note carrying a prescription no configured class covers shows nothing, which is the
    whole of what the feedback of 2026-08-25 asked for.
    """
    from canvas_sdk.test_utils.factories import NoteFactory

    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    bare_note = NoteFactory(patient=patient)

    with _catalogue_answers(ACE_PATH):
        button = EnrollmentButton(show_event(bare_note.dbid))
        assert button.visible() is False
        assert button.compute() == []


def test_a_show_event_carrying_no_note_shows_nothing(medication_class):
    """Covers scenario: AC21, the enrolment control stays hidden when no prescription matches. Covers criterion: AC21.

    The control is asked about in places that hand over no note. Answering yes there would
    put it on a header with nothing behind it, and raising would take the whole header
    down rather than one control.
    """
    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    assert EnrollmentButton(show_event(None)).visible() is False


def test_the_control_sits_in_the_note_header():
    """Covers criterion: AC20.

    The header rather than the footer, which is where it used to be. The move and the
    eligibility gate arrived together, because a control inline with the note's own title
    is only tolerable when it is absent for the notes it has nothing to offer.
    """
    from canvas_sdk.handlers.action_button import ActionButton

    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    assert EnrollmentButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER


def test_clicking_opens_the_form_in_the_right_chart_pane():
    """Covers scenario: AC30, the enrolment form opens in the right chart pane rather than a modal. Covers criterion: AC30.

    A modal would cover the note the provider reads in order to decide what to enrol on,
    which is the reason this is a pane and the reason that choice is worth a test rather
    than a comment somebody can quietly reverse.
    """
    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    event = make_event(
        "ACTION_BUTTON_CLICKED",
        context={"key": EnrollmentButton.BUTTON_KEY, "note_id": "note-42"},
    )

    opened = payload(EnrollmentButton(event).compute()[0])

    assert opened["target"] == "right_chart_pane"
    assert opened["target"] != "default_modal"


def test_the_form_it_opens_names_the_note_it_was_clicked_from():
    """Covers scenario: AC30, the enrolment form opens in the right chart pane rather than a modal. Covers criterion: AC30."""
    from medication_followup_protocol.handlers.enrollment_button import EnrollmentButton

    event = make_event(
        "ACTION_BUTTON_CLICKED",
        context={"key": EnrollmentButton.BUTTON_KEY, "note_id": "note-42"},
    )

    opened = payload(EnrollmentButton(event).compute()[0])

    assert "note-42" in opened["url"]
