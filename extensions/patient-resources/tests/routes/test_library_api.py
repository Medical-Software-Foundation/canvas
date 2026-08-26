"""Library reads and curation over HTTP.

The recurring assertion is that a refusal writes nothing: hiding a control in the
front end is convenience, and the server is the enforcement.
"""

from unittest.mock import MagicMock, patch

import pytest

from patient_resources.constants import (
    MAX_PAGE_SIZE,
    NOTE_MAX_CHARS,
    SECRET_ADMIN_ROLE_DOMAINS,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
)
from patient_resources.models import PatientResource
from patient_resources.routes.library_api import LibraryAPI

VALID = {"title": "Managing diabetes", "url": "https://example.org/d", "label": "Diabetes"}


def _api(make_request, *, secrets=None, **kwargs):
    api = LibraryAPI.__new__(LibraryAPI)
    api.secrets = {} if secrets is None else secrets
    api.request = make_request(**kwargs)
    return api


def _resource(dbid=12):
    resource = MagicMock()
    resource.dbid = dbid
    resource.title = "Managing diabetes"
    resource.url = "https://example.org/d"
    resource.label = "Diabetes"
    resource.status = STATUS_ACTIVE
    resource.created_at = None
    resource.updated_at = None
    return resource


@pytest.fixture(autouse=True)
def _reset():
    PatientResource.objects.reset_mock()
    yield


def _as(staff, *, admin):
    """Patch the two things every route consults: who is calling, and may they curate."""
    return (
        patch("patient_resources.routes.support.staff_from_session", return_value=staff),
        patch("patient_resources.routes.library_api.is_library_admin", return_value=admin),
    )


def _call(method_name, staff, admin, make_request, **request_kwargs):
    session, permission = _as(staff, admin=admin)
    with session, permission:
        api = _api(make_request, **request_kwargs)
        return getattr(api, method_name)()


# --- authentication -------------------------------------------------------

WRITE_ROUTES = [
    "post_resource",
    "put_resource",
    "archive_resource",
    "restore_resource",
    "retract_resource",
    "delete_resource_route",
]
ALL_ROUTES = ["get_resources", "get_labels", *WRITE_ROUTES]


@pytest.mark.parametrize("route", ALL_ROUTES)
def test_every_route_401s_without_a_resolvable_staff_member(route, make_request):
    responses = _call(route, None, False, make_request, json_body=dict(VALID))
    assert responses[0].status_code == 401


@pytest.mark.parametrize("route", WRITE_ROUTES)
def test_every_write_route_403s_for_a_non_admin_and_writes_nothing(
    route, mock_staff, make_request
):
    with patch(
        "patient_resources.routes.library_api.get_resource", return_value=_resource()
    ):
        responses = _call(route, mock_staff, False, make_request, json_body=dict(VALID))
    assert responses[0].status_code == 403
    PatientResource.objects.create.assert_not_called()


# --- listing --------------------------------------------------------------


def test_listing_reports_whether_the_caller_may_edit(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.list_resources", return_value=([], 0)
    ):
        for admin in (True, False):
            responses = _call("get_resources", mock_staff, admin, make_request)
            assert responses[0].data["can_edit"] is admin


def test_a_non_admin_cannot_reveal_archived_rows_with_a_query_param(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.list_resources", return_value=([], 0)
    ) as listing:
        _call(
            "get_resources",
            mock_staff,
            False,
            make_request,
            query_params={"include_archived": "true"},
        )
    assert listing.call_args.kwargs["include_archived"] is False


def test_a_curator_can_include_archived_rows(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.list_resources", return_value=([], 0)
    ) as listing:
        _call(
            "get_resources",
            mock_staff,
            True,
            make_request,
            query_params={"include_archived": "TRUE"},
        )
    assert listing.call_args.kwargs["include_archived"] is True


def test_paging_parameters_are_clamped(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.list_resources", return_value=([], 0)
    ) as listing:
        _call(
            "get_resources",
            mock_staff,
            True,
            make_request,
            query_params={"limit": "99999", "offset": "-4"},
        )
    assert listing.call_args.kwargs["limit"] == MAX_PAGE_SIZE
    assert listing.call_args.kwargs["offset"] == 0


def test_labels_are_returned_for_the_filter(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.distinct_labels", return_value=["Cardiac"]
    ):
        assert _call("get_labels", mock_staff, False, make_request)[0].data == {
            "labels": ["Cardiac"]
        }


# --- create ---------------------------------------------------------------


@pytest.mark.parametrize("body", [[], "text", None, 42])
def test_a_non_object_body_is_a_400_not_a_crash(body, mock_staff, make_request):
    responses = _call("post_resource", mock_staff, True, make_request, json_body=body)
    assert responses[0].status_code == 400


def test_a_malformed_body_is_a_400(mock_staff, make_request):
    request = make_request()
    request.json.side_effect = ValueError("not json")
    session, permission = _as(mock_staff, admin=True)
    with session, permission:
        api = LibraryAPI.__new__(LibraryAPI)
        api.secrets = {}
        api.request = request
        assert api.post_resource()[0].status_code == 400


def test_field_errors_come_back_keyed_by_field(mock_staff, make_request):
    responses = _call(
        "post_resource",
        mock_staff,
        True,
        make_request,
        json_body={"title": "", "url": "javascript:alert(1)", "label": ""},
    )
    assert responses[0].status_code == 400
    assert set(responses[0].data["field_errors"]) == {"title", "url"}


def test_an_unsafe_link_is_refused_and_nothing_is_written(mock_staff, make_request):
    _call(
        "post_resource",
        mock_staff,
        True,
        make_request,
        json_body={"title": "T", "url": "javascript:alert(1)"},
    )
    PatientResource.objects.create.assert_not_called()


def test_a_valid_resource_is_created_and_attributed(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.create_resource", return_value=_resource()
    ) as create:
        responses = _call(
            "post_resource", mock_staff, True, make_request, json_body=dict(VALID)
        )
    assert responses[0].status_code == 201
    assert create.call_args.kwargs["staff_dbid"] == mock_staff.dbid


def test_the_default_note_reaches_the_catalog(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.create_resource", return_value=_resource()
    ) as create:
        _call(
            "post_resource",
            mock_staff,
            True,
            make_request,
            json_body=dict(VALID, default_note="Read the first two pages."),
        )
    assert create.call_args.kwargs["default_note"] == "Read the first two pages."


def test_a_resource_can_be_added_without_a_default_note(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.create_resource", return_value=_resource()
    ) as create:
        _call("post_resource", mock_staff, True, make_request, json_body=dict(VALID))
    assert create.call_args.kwargs["default_note"] == ""


def test_an_over_long_default_note_is_a_400_against_its_own_field(
    mock_staff, make_request
):
    """Keyed as `default_note` so the message lands beside the textarea."""
    responses = _call(
        "post_resource",
        mock_staff,
        True,
        make_request,
        json_body=dict(VALID, default_note="n" * (NOTE_MAX_CHARS + 1)),
    )
    assert responses[0].status_code == 400
    assert set(responses[0].data["field_errors"]) == {"default_note"}
    PatientResource.objects.create.assert_not_called()


def test_editing_a_resource_carries_the_default_note(mock_staff, make_request):
    with patch(
        "patient_resources.routes.library_api.get_resource", return_value=_resource()
    ), patch(
        "patient_resources.routes.library_api.update_resource", return_value=_resource()
    ) as update:
        _call(
            "put_resource",
            mock_staff,
            True,
            make_request,
            path_params={"resource_id": "12"},
            json_body=dict(VALID, default_note="A better default."),
        )
    assert update.call_args.kwargs["default_note"] == "A better default."


def test_a_duplicate_is_a_409(mock_staff, make_request):
    from patient_resources.services.catalog import DuplicateResourceError

    with patch(
        "patient_resources.routes.library_api.create_resource",
        side_effect=DuplicateResourceError("already exists"),
    ):
        responses = _call(
            "post_resource", mock_staff, True, make_request, json_body=dict(VALID)
        )
    assert responses[0].status_code == 409


# --- update ---------------------------------------------------------------


def test_editing_a_missing_resource_is_a_404(mock_staff, make_request):
    with patch("patient_resources.routes.library_api.get_resource", return_value=None):
        responses = _call(
            "put_resource", mock_staff, True, make_request, json_body=dict(VALID)
        )
    assert responses[0].status_code == 404


def test_changing_a_shared_resources_link_is_a_409(mock_staff, make_request):
    """The link is the identity of what a patient was given."""
    from patient_resources.services.catalog import ResourceInUseError

    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch(
            "patient_resources.routes.library_api.update_resource",
            side_effect=ResourceInUseError("already shared"),
        ),
    ):
        responses = _call(
            "put_resource", mock_staff, True, make_request, json_body=dict(VALID)
        )
    assert responses[0].status_code == 409


# --- lifecycle ------------------------------------------------------------


def test_archiving_sets_the_archived_status(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch(
            "patient_resources.routes.library_api.set_status", return_value=_resource()
        ) as set_status,
    ):
        _call("archive_resource", mock_staff, True, make_request)
    assert set_status.call_args.args[1] == STATUS_ARCHIVED


def test_restoring_sets_the_active_status(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch(
            "patient_resources.routes.library_api.set_status", return_value=_resource()
        ) as set_status,
    ):
        _call("restore_resource", mock_staff, True, make_request)
    assert set_status.call_args.args[1] == STATUS_ACTIVE


def test_retracting_withdraws_from_patients_and_archives(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch("patient_resources.routes.library_api.set_status", return_value=_resource()),
        patch("patient_resources.routes.library_api.has_live_shares", return_value=True),
        patch(
            "patient_resources.routes.library_api.revoke_resource_shares", return_value=7
        ) as revoke,
    ):
        responses = _call(
            "retract_resource",
            mock_staff,
            True,
            make_request,
            json_body={"reason": "Broken link"},
        )
    assert responses[0].data["withdrawn"] == 7
    assert revoke.call_args.kwargs["reason"] == "Broken link"


def test_retracting_without_a_body_still_works(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch("patient_resources.routes.library_api.set_status", return_value=_resource()),
        patch("patient_resources.routes.library_api.has_live_shares", return_value=True),
        patch("patient_resources.routes.library_api.revoke_resource_shares", return_value=0),
    ):
        responses = _call("retract_resource", mock_staff, True, make_request, json_body=None)
    assert responses[0].status_code == 200


# --- gating is read from config, not assumed ------------------------------


def test_disabled_role_config_denies_curation_end_to_end(mock_staff, make_request):
    """No patch on is_library_admin here: the real check runs."""
    from canvas_sdk.v1.data.staff import StaffRole

    StaffRole.objects.filter.return_value.exists.return_value = True
    with patch("patient_resources.routes.support.staff_from_session", return_value=mock_staff):
        api = _api(
            make_request,
            secrets={SECRET_ADMIN_ROLE_DOMAINS: "NONE"},
            json_body=dict(VALID),
        )
        responses = api.post_resource()
    assert responses[0].status_code == 403
    PatientResource.objects.create.assert_not_called()


# --- update, remaining paths ----------------------------------------------


def test_a_valid_edit_returns_the_updated_resource(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch(
            "patient_resources.routes.library_api.update_resource", return_value=_resource()
        ) as update,
    ):
        responses = _call(
            "put_resource", mock_staff, True, make_request, json_body=dict(VALID)
        )
    assert responses[0].status_code == 200
    assert responses[0].data["id"] == 12
    assert update.call_args.kwargs["staff_dbid"] == mock_staff.dbid


@pytest.mark.parametrize("body", [[], "text", 7])
def test_editing_with_a_non_object_body_is_a_400(body, mock_staff, make_request):
    with patch("patient_resources.routes.library_api.get_resource", return_value=_resource()):
        responses = _call("put_resource", mock_staff, True, make_request, json_body=body)
    assert responses[0].status_code == 400


def test_editing_with_invalid_fields_reports_them(mock_staff, make_request):
    with patch("patient_resources.routes.library_api.get_resource", return_value=_resource()):
        responses = _call(
            "put_resource",
            mock_staff,
            True,
            make_request,
            json_body={"title": "", "url": "javascript:alert(1)"},
        )
    assert responses[0].status_code == 400
    assert set(responses[0].data["field_errors"]) == {"title", "url"}


@pytest.mark.parametrize("route", ["archive_resource", "restore_resource", "retract_resource"])
def test_lifecycle_routes_404_on_a_missing_resource(route, mock_staff, make_request):
    with patch("patient_resources.routes.library_api.get_resource", return_value=None):
        responses = _call(route, mock_staff, True, make_request)
    assert responses[0].status_code == 404


# --- delete ---------------------------------------------------------------


def test_delete_403s_for_a_non_admin_and_removes_nothing(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch("patient_resources.routes.library_api.delete_resource") as remove,
    ):
        responses = _call("delete_resource_route", mock_staff, False, make_request)
    assert responses[0].status_code == 403
    remove.assert_not_called()


def test_delete_404s_on_a_missing_resource(mock_staff, make_request):
    with patch("patient_resources.routes.library_api.get_resource", return_value=None):
        responses = _call("delete_resource_route", mock_staff, True, make_request)
    assert responses[0].status_code == 404


def test_a_never_shared_resource_is_deleted(mock_staff, make_request):
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch("patient_resources.routes.library_api.delete_resource") as remove,
    ):
        responses = _call("delete_resource_route", mock_staff, True, make_request)
    assert responses[0].status_code == 200
    assert responses[0].data == {"deleted": True, "id": 12}
    remove.assert_called_once()


def test_deleting_a_shared_resource_is_a_409(mock_staff, make_request):
    """Refused, with the message naming Withdraw and Archive instead."""
    from patient_resources.services.catalog import ResourceInUseError

    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch(
            "patient_resources.routes.library_api.delete_resource",
            side_effect=ResourceInUseError("shared with patients"),
        ),
    ):
        responses = _call("delete_resource_route", mock_staff, True, make_request)
    assert responses[0].status_code == 409


# --- the flag that chooses the control ------------------------------------


def test_the_listing_tells_a_curator_which_rows_a_patient_still_holds(mock_staff, make_request):
    with (
        patch(
            "patient_resources.routes.library_api.list_resources",
            return_value=([_resource(12), _resource(15)], 2),
        ),
        patch(
            "patient_resources.routes.library_api.resources_with_live_shares", return_value={12}
        ) as lookup,
        patch(
            "patient_resources.routes.library_api.resources_with_withdrawn_shares",
            return_value=set(),
        ),
    ):
        data = _call("get_resources", mock_staff, True, make_request)[0].data

    assert [r["has_live_shares"] for r in data["resources"]] == [True, False]
    # One lookup for the page, not one per row.
    assert lookup.call_count == 1
    assert lookup.call_args.args[0] == [12, 15]


def test_a_non_curator_gets_no_flag_and_costs_no_query(mock_staff, make_request):
    """They see no destructive controls, so the flag would be dead weight."""
    with (
        patch(
            "patient_resources.routes.library_api.list_resources",
            return_value=([_resource(12)], 1),
        ),
        patch("patient_resources.routes.library_api.resources_with_live_shares") as lookup,
        patch(
            "patient_resources.routes.library_api.resources_with_withdrawn_shares"
        ) as withdrawn_lookup,
    ):
        data = _call("get_resources", mock_staff, False, make_request)[0].data

    assert "has_live_shares" not in data["resources"][0]
    assert "has_withdrawn_shares" not in data["resources"][0]
    lookup.assert_not_called()
    withdrawn_lookup.assert_not_called()


def test_the_listing_says_which_rows_were_withdrawn_rather_than_just_archived(
    mock_staff, make_request
):
    """Withdrawing archives the resource, so without this flag a row that was
    taken back off patients is indistinguishable from one merely retired.
    """
    with (
        patch(
            "patient_resources.routes.library_api.list_resources",
            return_value=([_resource(12), _resource(15)], 2),
        ),
        patch(
            "patient_resources.routes.library_api.resources_with_live_shares",
            return_value={12, 15},
        ),
        patch(
            "patient_resources.routes.library_api.resources_with_withdrawn_shares",
            return_value={12},
        ),
    ):
        data = _call("get_resources", mock_staff, True, make_request)[0].data

    assert [r["has_withdrawn_shares"] for r in data["resources"]] == [True, False]


def test_both_share_lookups_run_once_for_the_page(mock_staff, make_request):
    with (
        patch(
            "patient_resources.routes.library_api.list_resources",
            return_value=([_resource(12), _resource(15)], 2),
        ),
        patch(
            "patient_resources.routes.library_api.resources_with_live_shares", return_value=set()
        ) as ever,
        patch(
            "patient_resources.routes.library_api.resources_with_withdrawn_shares",
            return_value=set(),
        ) as withdrawn,
    ):
        _call("get_resources", mock_staff, True, make_request)

    assert ever.call_count == 1
    assert withdrawn.call_count == 1
    assert ever.call_args.args[0] == withdrawn.call_args.args[0] == [12, 15]


def test_withdrawing_with_nothing_left_to_withdraw_is_a_409(mock_staff, make_request):
    """The row hides the control in this state, but a direct request must not
    succeed at doing nothing.

    Without the guard the call revokes zero rows, re-archives an already archived
    resource, and reports success.
    """
    with (
        patch("patient_resources.routes.library_api.get_resource", return_value=_resource()),
        patch("patient_resources.routes.library_api.has_live_shares", return_value=False),
        patch(
            "patient_resources.routes.library_api.revoke_resource_shares"
        ) as revoke,
        patch("patient_resources.routes.library_api.set_status") as status,
    ):
        responses = _call("retract_resource", mock_staff, True, make_request)

    assert responses[0].status_code == 409
    revoke.assert_not_called()
    status.assert_not_called()
