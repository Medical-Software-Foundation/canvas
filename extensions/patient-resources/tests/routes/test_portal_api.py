"""The patient's own resource list.

This is the endpoint any signed-in patient can reach, so most of these tests are
about what it refuses.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from canvas_sdk.v1.data import Patient

from patient_resources.constants import SESSION_ID_HEADER, STATUS_ACTIVE
from patient_resources.models import PatientResourceShare
from patient_resources.routes.portal_api import PortalAPI

WHEN = datetime(2026, 8, 20, 14, 3, 11, tzinfo=timezone.utc)


def _api(make_request, **kwargs):
    api = PortalAPI.__new__(PortalAPI)
    api.secrets = {}
    api.request = make_request(**kwargs)
    return api


def _share(title="Managing diabetes", live_title=None):
    share = MagicMock()
    # The live catalog row the payload now reads its title and label from.
    # Defaults to matching the snapshot; a test passes live_title to prove a
    # correction reaches the patient.
    share.resource = MagicMock()
    share.resource.title = live_title or title
    share.resource.label = "Diabetes"
    share.title_at_share = title
    share.url_at_share = "https://example.org/d"
    share.label_at_share = "Diabetes"
    share.shared_at = WHEN
    share.revoked_at = None
    return share


def _signed_in(patient):
    Patient.objects.reset_mock()
    Patient.objects.filter.return_value.only.return_value.first.return_value = patient


def _rows(live=(), revoked=()):
    """Arrange the two portal queries.

    They are told apart by their chains rather than by inspecting filter
    arguments: the live list joins the catalog row it reads the title from, and
    the withdrawn list does not.
    """
    PatientResourceShare.objects.reset_mock(side_effect=True, return_value=True)
    manager = PatientResourceShare.objects.filter.return_value

    live_chain = manager.select_related.return_value.order_by.return_value
    live_chain.__getitem__.return_value = list(live)

    revoked_chain = manager.order_by.return_value
    revoked_chain.__getitem__.return_value = list(revoked)

    manager.update.return_value = 0


def test_unresolvable_patient_is_a_401_not_an_empty_list(make_request):
    """An empty list would tell a patient their care team shared nothing."""
    _signed_in(None)
    responses = _api(make_request, headers={SESSION_ID_HEADER: "nobody"}).get_my_resources()
    assert responses[0].status_code == 401
    assert "resources" not in getattr(responses[0], "data", {})


def test_missing_session_header_is_a_401(make_request):
    _signed_in(None)
    assert _api(make_request).get_my_resources()[0].status_code == 401


def test_the_query_is_scoped_to_the_resolved_patient(mock_patient, make_request):
    _signed_in(mock_patient)
    _rows(live=[_share()])
    _api(make_request, headers={SESSION_ID_HEADER: mock_patient.id}).get_my_resources()

    first_call = PatientResourceShare.objects.filter.call_args_list[0].kwargs
    assert first_call["patient__dbid"] == mock_patient.dbid
    assert first_call["revoked_at__isnull"] is True
    assert first_call["resource__status"] == STATUS_ACTIVE


def test_a_patient_query_param_is_ignored(mock_patient, make_request):
    """The route takes no identifier, so there is nothing to tamper with."""
    _signed_in(mock_patient)
    _rows(live=[_share()])
    _api(
        make_request,
        headers={SESSION_ID_HEADER: mock_patient.id},
        query_params={"patient": "00000000000000000000000000000099"},
    ).get_my_resources()

    for call in PatientResourceShare.objects.filter.call_args_list:
        assert call.kwargs["patient__dbid"] == mock_patient.dbid


def test_a_corrected_title_reaches_the_patient(mock_patient, make_request):
    """Editing a shared resource's title has to show in the portal.

    The link is frozen once shared, so the correction can only ever redescribe
    the same resource.
    """
    _signed_in(mock_patient)
    _rows(live=[_share(title="Managing diabtes", live_title="Managing diabetes")])
    data = _api(
        make_request, headers={SESSION_ID_HEADER: mock_patient.id}
    ).get_my_resources()[0].data
    assert data["resources"][0]["title"] == "Managing diabetes"


def test_the_list_projects_the_share(mock_patient, make_request):
    _signed_in(mock_patient)
    _rows(live=[_share()])
    data = _api(make_request, headers={SESSION_ID_HEADER: mock_patient.id}).get_my_resources()[0].data
    assert data["resources"] == [
        {
            "title": "Managing diabetes",
            "label": "Diabetes",
            "url": "https://example.org/d",
            "shared_at": "2026-08-20T14:03:11+00:00",
        }
    ]


def test_withdrawn_resources_are_reported_separately(mock_patient, make_request):
    """A patient should see that something was withdrawn, not just fewer items."""
    _signed_in(mock_patient)
    withdrawn = _share("Old handout")
    withdrawn.revoked_at = WHEN
    _rows(live=[], revoked=[withdrawn])

    data = _api(make_request, headers={SESSION_ID_HEADER: mock_patient.id}).get_my_resources()[0].data
    assert data["resources"] == []
    assert data["withdrawn"][0]["title"] == "Old handout"
    assert "url" not in data["withdrawn"][0]


def test_an_empty_list_is_a_200(mock_patient, make_request):
    _signed_in(mock_patient)
    _rows()
    response = _api(make_request, headers={SESSION_ID_HEADER: mock_patient.id}).get_my_resources()[0]
    assert response.status_code == 200
    assert response.data["resources"] == []
    assert response.data["truncated"] is False


def test_opening_the_list_marks_it_viewed(mock_patient, make_request):
    """By patient, never by row: a row id is the shape of a cross-patient leak."""
    _signed_in(mock_patient)
    _rows(live=[_share()])
    _api(make_request, headers={SESSION_ID_HEADER: mock_patient.id}).get_my_resources()

    update_calls = [
        call
        for call in PatientResourceShare.objects.filter.call_args_list
        if call.kwargs.get("first_viewed_at__isnull") is True
    ]
    assert update_calls
    assert update_calls[0].kwargs["patient__dbid"] == mock_patient.dbid


def test_nothing_is_marked_viewed_for_an_unauthenticated_request(make_request):
    _signed_in(None)
    _rows()
    _api(make_request).get_my_resources()
    PatientResourceShare.objects.filter.assert_not_called()
