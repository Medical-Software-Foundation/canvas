"""Whether a class covers a prescription, which is what gates the note header control.

The ontologies service is faked in every test here. A unit test that needs a running
catalogue is not a unit test, and the seam is `_classification_path`'s single call to
`ontologies_http.get_json`, so that is what gets patched rather than anything deeper.

The classification paths used below are the real ones from the local catalogue rather
than invented numbers. Lisinopril at 10 mg and at 20 mg genuinely carry the identical
path, which is what makes the group matching case a real one rather than a fixture
arranged to pass.
"""

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make

#: Lisinopril, both strengths, as the local catalogue carries it.
ACE_PATH = [2549, 3050, 24, 3064]

#: Warfarin, a different branch of the same tree, so it shares no prefix with the above.
ANTICOAGULANT_PATH = [2549, 3054, 28, 3068]


@pytest.fixture
def committed_prescription(patient, staff):
    """Put a committed prescription on a fresh note and hand back the note and the code."""
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding

    def _make(fdb_code="fdb-lisinopril-20", coded=True):
        note = NoteFactory(patient=patient)
        medication = MedicationFactory(patient=patient)
        if coded:
            make(
                MedicationCoding,
                medication=medication,
                display="lisinopril 20 mg tablet",
                system="http://www.fdbhealth.com/",
                code=fdb_code,
            )
        PrescriptionFactory(
            patient=patient,
            prescriber=staff,
            medication=medication,
            note=note,
            committer=CanvasUserFactory(),
        )
        return note

    return _make


def _coverage(medication_class, kind, **fields):
    """One coverage entry on a class."""
    from medication_followup_protocol.models import MedicationClassCoverage

    return MedicationClassCoverage.objects.create(
        medication_class=medication_class, kind=kind, **fields
    )


def _with_path(path):
    """Patch the ontologies lookup to answer with one classification path."""
    from medication_followup_protocol.services import eligibility

    response = MagicMock()
    response.json.return_value = {"etc_path_id": path} if path is not None else {}
    return patch.object(eligibility.ontologies_http, "get_json", return_value=response)


def test_a_group_entry_matches_a_product_nobody_picked(medication_class, committed_prescription):
    """Covers scenario: AC23, a group coverage entry matches a product that was never picked individually. Covers criterion: AC23.

    The practice searched the catalogue and picked lisinopril 10 mg, so that product's own
    path is what got stored. The prescription in front of the provider is the 20 mg
    strength, a product nobody picked, and it matches because its own path begins with the
    stored one.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["Cardiovascular Agents", "ACE Inhibitors", "Lisinopril", "Lisinopril"],
        display_name="lisinopril 10 mg tablet",
    )
    note = committed_prescription()

    with _with_path(ACE_PATH):
        matched = eligibility.matching_classes(note.dbid)

    assert medication_class in matched


def test_a_group_entry_does_not_match_a_different_branch(medication_class, committed_prescription):
    """Covers criterion: AC23.

    The stored path and the prescription's path share only their first element, so the
    prefix test fails and nothing matches. Without this the rule would read as matching
    anything under the same root, which would put every cardiovascular drug on an
    anticoagulant programme.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ANTICOAGULANT_PATH,
        etc_path_name=["Anti", "Coag", "War", "Farin"],
        display_name="warfarin 2.5 mg tablet",
    )
    note = committed_prescription()

    with _with_path(ACE_PATH):
        assert eligibility.matching_classes(note.dbid) == []


def test_a_product_entry_matches_only_its_own_code(medication_class, committed_prescription):
    """Covers criterion: AC23.

    A product entry is the narrow case, one exact product rather than a class of
    medication, so it matches on the FDB code and ignores the path entirely.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.PRODUCT,
        med_medication_id="fdb-lisinopril-20",
        display_name="lisinopril 20 mg tablet",
    )
    note = committed_prescription(fdb_code="fdb-lisinopril-20")

    with _with_path(ACE_PATH):
        assert medication_class in eligibility.matching_classes(note.dbid)

    other = committed_prescription(fdb_code="fdb-something-else")
    with _with_path(ACE_PATH):
        assert eligibility.matching_classes(other.dbid) == []


def test_the_control_shows_once_a_prescription_matches(medication_class, committed_prescription):
    """Covers scenario: AC20, the enrolment control shows once a prescription matches a class's coverage. Covers criterion: AC20."""
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["a", "b", "c", "d"],
        display_name="lisinopril 10 mg tablet",
    )
    note = committed_prescription()

    with _with_path(ACE_PATH):
        assert eligibility.has_matching_prescription(note.dbid) is True


def test_the_control_stays_hidden_when_nothing_matches(medication_class, committed_prescription):
    """Covers scenario: AC21, the enrolment control stays hidden when no prescription matches. Covers criterion: AC21.

    The class carries coverage for a different branch, so the note's prescription matches
    nothing and the control has no reason to appear.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ANTICOAGULANT_PATH,
        etc_path_name=["a", "b", "c", "d"],
        display_name="warfarin 2.5 mg tablet",
    )
    note = committed_prescription()

    with _with_path(ACE_PATH):
        assert eligibility.has_matching_prescription(note.dbid) is False


def test_a_prescription_with_no_coding_is_skipped(medication_class, committed_prescription):
    """Covers criterion: AC21.

    A compound formulation carries no FDB coding, and the specification says a
    prescription like that matches nothing rather than raising. Asserted because the
    failure mode without it is an exception on the show event, which would take the whole
    note header down rather than one control.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["a", "b", "c", "d"],
        display_name="lisinopril 10 mg tablet",
    )
    note = committed_prescription(coded=False)

    with _with_path(ACE_PATH):
        assert eligibility.has_matching_prescription(note.dbid) is False


def test_a_code_the_catalogue_does_not_know_is_skipped(medication_class, committed_prescription):
    """Covers criterion: AC21.

    The service answering with nothing for a code is a fact about the catalogue rather
    than a plugin failure, so it reads as no match rather than an error.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["a", "b", "c", "d"],
        display_name="lisinopril 10 mg tablet",
    )
    note = committed_prescription()

    with _with_path(None):
        assert eligibility.has_matching_prescription(note.dbid) is False


def test_an_inactive_class_covers_nothing(medication_class, committed_prescription):
    """Covers criterion: AC20.

    Making a class inactive retires it, and a retired class must stop offering itself on
    new notes while its running enrolments finish, so the match reads active classes only.
    """
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["a", "b", "c", "d"],
        display_name="lisinopril 10 mg tablet",
    )
    medication_class.active = False
    medication_class.save()
    note = committed_prescription()

    with _with_path(ACE_PATH):
        assert eligibility.matching_classes(note.dbid) == []


def test_one_code_costs_the_catalogue_one_lookup(medication_class, patient, staff):
    """Covers criterion: AC20.

    Two prescriptions on one note for the same medication share a code, and the walk
    looks that code up once rather than once per prescription. Asserted because the cost
    of getting this wrong is paid against an external service on every note render.
    """
    from canvas_sdk.test_utils.factories import (
        CanvasUserFactory,
        MedicationFactory,
        NoteFactory,
        PrescriptionFactory,
    )
    from canvas_sdk.v1.data import MedicationCoding
    from medication_followup_protocol.models import CoverageKind
    from medication_followup_protocol.services import eligibility

    _coverage(
        medication_class,
        CoverageKind.GROUP,
        etc_path_id=ACE_PATH,
        etc_path_name=["a", "b", "c", "d"],
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
    for _ in range(2):
        PrescriptionFactory(
            patient=patient,
            prescriber=staff,
            medication=medication,
            note=note,
            committer=CanvasUserFactory(),
        )

    with _with_path(ACE_PATH) as get_json:
        eligibility.matching_classes(note.dbid)

    assert get_json.call_count == 1
