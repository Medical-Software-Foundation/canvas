"""Session identity resolution."""

import uuid
from unittest.mock import MagicMock

from canvas_sdk.v1.data import Patient, Staff

from patient_resources.constants import SESSION_ID_HEADER
from patient_resources.services.identity import (
    id_candidates,
    patient_from_session,
    staff_from_session,
)

DASHED = "3f040d58-0000-4000-8000-000000000001"
UNDASHED = DASHED.replace("-", "")


def test_dashed_input_yields_the_undashed_form():
    assert UNDASHED in id_candidates(DASHED)


def test_undashed_input_yields_the_canonical_dashed_form():
    """The case a naive two-element set misses.

    Without parsing through uuid.UUID, an undashed header would only ever be
    tried undashed and would never match a dashed record.
    """
    assert DASHED in id_candidates(UNDASHED)


def test_non_uuid_input_still_yields_the_literal():
    """Nothing guarantees these 32-char keys are UUID-shaped."""
    assert id_candidates("not-a-uuid") == {"not-a-uuid", "notauuid"}


def test_blank_input_yields_nothing():
    for raw in ("", "   ", None):
        assert id_candidates(raw) == set()


def test_uuid_forms_all_collapse_to_the_same_candidate_set():
    assert id_candidates(DASHED) == id_candidates(UNDASHED) == id_candidates(str(uuid.UUID(DASHED)))


def _request(headers=None):
    request = MagicMock()
    request.headers = headers or {}
    return request


def test_blank_header_resolves_to_none_without_querying():
    Staff.objects.reset_mock()
    assert staff_from_session(_request({SESSION_ID_HEADER: ""})) is None
    Staff.objects.filter.assert_not_called()


def test_missing_header_resolves_to_none():
    assert staff_from_session(_request({})) is None


def test_staff_resolution_queries_staff_with_every_candidate(mock_staff):
    Staff.objects.reset_mock()
    Staff.objects.filter.return_value.only.return_value.first.return_value = mock_staff

    assert staff_from_session(_request({SESSION_ID_HEADER: DASHED})) is mock_staff

    passed = set(Staff.objects.filter.call_args.kwargs["id__in"])
    assert passed == id_candidates(DASHED)


def test_patient_resolution_queries_patient_not_staff(mock_patient):
    """A helper pointed at the wrong model 401s every patient in the portal.

    The header name is identical on both surfaces, so nothing else catches this.
    """
    Patient.objects.reset_mock()
    Staff.objects.reset_mock()
    Patient.objects.filter.return_value.only.return_value.first.return_value = mock_patient

    assert patient_from_session(_request({SESSION_ID_HEADER: DASHED})) is mock_patient
    Patient.objects.filter.assert_called_once()
    Staff.objects.filter.assert_not_called()


def test_unmatched_id_resolves_to_none_rather_than_a_placeholder():
    Staff.objects.filter.return_value.only.return_value.first.return_value = None
    assert staff_from_session(_request({SESSION_ID_HEADER: DASHED})) is None
