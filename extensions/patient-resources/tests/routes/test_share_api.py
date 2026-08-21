"""Patient lookup and sending, over HTTP."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.v1.data import Patient
from django.db import IntegrityError

from patient_resources.constants import MAX_SHARE_BATCH
from patient_resources.routes.share_api import ShareAPI
from patient_resources.services.identity import id_candidates
from patient_resources.services.shares import ShareResult

WHEN = datetime(2026, 8, 20, 14, 3, 11, tzinfo=timezone.utc)
DASHED = "3f040d58-0000-4000-8000-000000000001"


def _api(make_request, **kwargs):
    api = ShareAPI.__new__(ShareAPI)
    api.secrets = {}
    api.request = make_request(**kwargs)
    return api


def _found(patient):
    Patient.objects.reset_mock()
    Patient.objects.filter.return_value.only.return_value.first.return_value = patient


def _created_row(resource_id=12):
    row = MagicMock()
    row.resource_id = resource_id
    row.title_at_share = "Managing diabetes"
    row.url_at_share = "https://example.org/d"
    row.label_at_share = "Diabetes"
    row.shared_at = WHEN
    return row


def _call(method, staff, make_request, **kwargs):
    with patch("patient_resources.routes.support.staff_from_session", return_value=staff):
        return getattr(_api(make_request, **kwargs), method)()


# --- patient lookup -------------------------------------------------------


def test_lookup_401s_without_a_resolvable_staff_member(make_request):
    assert _call("get_patient", None, make_request)[0].status_code == 401


def test_lookup_404s_for_an_unknown_patient(mock_staff, make_request):
    _found(None)
    responses = _call(
        "get_patient", mock_staff, make_request, path_params={"patient_id": "nobody"}
    )
    assert responses[0].status_code == 404


def test_lookup_tries_every_key_form(mock_staff, mock_patient, make_request):
    """Patient.id is a 32-character CharField, so a dashed key misses otherwise."""
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.live_shares_for_patient", return_value=[]
    ):
        _call(
            "get_patient", mock_staff, make_request, path_params={"patient_id": DASHED}
        )
    assert set(Patient.objects.filter.call_args.kwargs["id__in"]) == id_candidates(DASHED)


def test_lookup_returns_the_name_and_what_they_already_have(
    mock_staff, mock_patient, make_request
):
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.live_shares_for_patient",
        return_value=[_created_row()],
    ):
        data = _call(
            "get_patient",
            mock_staff,
            make_request,
            path_params={"patient_id": mock_patient.id},
        )[0].data
    assert data["patient"]["name"] == "Jordan Lee"
    assert data["shared"][0]["resource_id"] == 12


def test_lookup_handles_a_patient_with_no_recorded_name(
    mock_staff, mock_patient, make_request
):
    """Rendering "None None" in a picker header is the failure this prevents."""
    mock_patient.first_name = None
    mock_patient.last_name = None
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.live_shares_for_patient", return_value=[]
    ):
        data = _call(
            "get_patient",
            mock_staff,
            make_request,
            path_params={"patient_id": mock_patient.id},
        )[0].data
    assert data["patient"]["name"] == ""


# --- sending --------------------------------------------------------------


def test_send_401s_without_a_resolvable_staff_member(make_request):
    responses = _call(
        "post_shares", None, make_request, json_body={"patient": "x", "resource_ids": [1]}
    )
    assert responses[0].status_code == 401


@pytest.mark.parametrize("body", [[], "text", 7])
def test_a_non_object_body_is_a_400(body, mock_staff, make_request):
    assert _call("post_shares", mock_staff, make_request, json_body=body)[0].status_code == 400


def test_a_json_null_body_is_a_400(mock_staff, make_request):
    """Set on the request directly: the fixture reads json_body=None as "no body"."""
    request = make_request()
    request.json.return_value = None
    with patch("patient_resources.routes.support.staff_from_session", return_value=mock_staff):
        api = ShareAPI.__new__(ShareAPI)
        api.secrets = {}
        api.request = request
        assert api.post_shares()[0].status_code == 400


def test_send_404s_for_an_unknown_patient(mock_staff, make_request):
    _found(None)
    responses = _call(
        "post_shares",
        mock_staff,
        make_request,
        json_body={"patient": "nobody", "resource_ids": [12]},
    )
    assert responses[0].status_code == 404


@pytest.mark.parametrize(
    "resource_ids",
    [None, [], "12", {"a": 1}, [12, "15"], [12, None], [12, 1.5]],
)
def test_bad_resource_ids_are_a_400(resource_ids, mock_staff, mock_patient, make_request):
    _found(mock_patient)
    responses = _call(
        "post_shares",
        mock_staff,
        make_request,
        json_body={"patient": mock_patient.id, "resource_ids": resource_ids},
    )
    assert responses[0].status_code == 400


def test_booleans_are_refused_rather_than_read_as_ids(mock_staff, mock_patient, make_request):
    """True is an int in Python and would otherwise share resource 1."""
    _found(mock_patient)
    responses = _call(
        "post_shares",
        mock_staff,
        make_request,
        json_body={"patient": mock_patient.id, "resource_ids": [True]},
    )
    assert responses[0].status_code == 400


def test_an_over_cap_batch_is_refused_by_the_api(mock_staff, mock_patient, make_request):
    """A direct API client bypasses the picker's own limit."""
    _found(mock_patient)
    responses = _call(
        "post_shares",
        mock_staff,
        make_request,
        json_body={
            "patient": mock_patient.id,
            "resource_ids": list(range(MAX_SHARE_BATCH + 1)),
        },
    )
    assert responses[0].status_code == 400
    assert str(MAX_SHARE_BATCH) in responses[0].data["error"]


def test_a_successful_send_reports_all_three_counts(mock_staff, mock_patient, make_request):
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.share_resources",
        return_value=ShareResult(
            created=[_created_row(12)], already_shared=1, skipped_unavailable=2
        ),
    ):
        data = _call(
            "post_shares",
            mock_staff,
            make_request,
            json_body={"patient": mock_patient.id, "resource_ids": [12, 15, 19, 20]},
        )[0].data
    assert data["created"] == 1
    assert data["already_shared"] == 1
    assert data["skipped_unavailable"] == 2
    assert data["shared_resource_ids"] == [12]


def test_the_sender_comes_from_the_session_not_the_body(
    mock_staff, mock_patient, make_request
):
    """A caller could otherwise attribute a share to anyone."""
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.share_resources",
        return_value=ShareResult(created=[], already_shared=0, skipped_unavailable=0),
    ) as share:
        _call(
            "post_shares",
            mock_staff,
            make_request,
            json_body={
                "patient": mock_patient.id,
                "resource_ids": [12],
                "staff_id": "somebody-else",
                "shared_by": 999,
            },
        )
    assert share.call_args.kwargs["staff_dbid"] == mock_staff.dbid


def test_a_concurrent_duplicate_send_is_reported_not_a_500(
    mock_staff, mock_patient, make_request
):
    """The pre-check races with a second provider; the constraint is the real guard."""
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.share_resources", side_effect=IntegrityError()
    ):
        response = _call(
            "post_shares",
            mock_staff,
            make_request,
            json_body={"patient": mock_patient.id, "resource_ids": [12]},
        )[0]
    assert response.status_code == 200
    assert response.data["created"] == 0
    assert response.data["already_shared"] == 1


def test_a_blank_patient_key_is_a_404_without_querying(mock_staff, make_request):
    """No candidates to try, so there is nothing to look up."""
    Patient.objects.reset_mock()
    responses = _call(
        "post_shares",
        mock_staff,
        make_request,
        json_body={"patient": "   ", "resource_ids": [12]},
    )
    assert responses[0].status_code == 404
    Patient.objects.filter.assert_not_called()


def test_a_missing_patient_key_in_the_path_is_a_404(mock_staff, make_request):
    Patient.objects.reset_mock()
    responses = _call("get_patient", mock_staff, make_request, path_params={})
    assert responses[0].status_code == 404
    Patient.objects.filter.assert_not_called()


# --- the patient card ------------------------------------------------------


def _lookup(mock_staff, mock_patient, make_request):
    _found(mock_patient)
    with patch(
        "patient_resources.routes.share_api.live_shares_for_patient", return_value=[]
    ):
        return _call(
            "get_patient",
            mock_staff,
            make_request,
            path_params={"patient_id": mock_patient.id},
        )[0].data["patient"]


def test_the_card_carries_name_dob_and_mrn(mock_staff, mock_patient, make_request):
    assert _lookup(mock_staff, mock_patient, make_request) == {
        "name": "Jordan Lee",
        "birth_date": "04/12/1979",
        "mrn": "88213",
    }


def test_birth_date_is_formatted_month_first(mock_staff, mock_patient, make_request):
    """Deliberately formatted server-side.

    toLocaleDateString follows the reader's locale, so an en-GB session would
    render this same date as 12/04/1979 -- the same digits reading as a different
    day in a US clinical record.
    """
    assert _lookup(mock_staff, mock_patient, make_request)["birth_date"] == "04/12/1979"


def test_a_missing_birth_date_is_empty_not_a_placeholder(
    mock_staff, mock_patient, make_request
):
    """The card joins these itself, so empty drops the separator.

    "DOB None" on a patient card is exactly the placeholder this repo's rules
    forbid.
    """
    mock_patient.birth_date = None
    assert _lookup(mock_staff, mock_patient, make_request)["birth_date"] == ""


def test_a_missing_mrn_is_empty(mock_staff, mock_patient, make_request):
    mock_patient.mrn = None
    assert _lookup(mock_staff, mock_patient, make_request)["mrn"] == ""


def test_identifiers_are_fetched_in_the_same_query(mock_staff, mock_patient, make_request):
    """No extra round trip to populate the card."""
    _lookup(mock_staff, mock_patient, make_request)
    only_fields = Patient.objects.filter.return_value.only.call_args.args
    assert "birth_date" in only_fields
    assert "mrn" in only_fields


def test_a_birth_date_stored_as_text_degrades_to_that_text(
    mock_staff, mock_patient, make_request
):
    """The DDL emits no column types beyond text for plugin tables, and this
    column belongs to Canvas rather than to us -- but a reader still has to
    tolerate a value that is not a date object rather than raising on it.
    """
    mock_patient.birth_date = "1979-04-12"
    assert _lookup(mock_staff, mock_patient, make_request)["birth_date"] == "1979-04-12"
