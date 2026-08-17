"""The staff-authenticated waitlist endpoints."""

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from scheduling_waitlist.routes.waitlist_api import WaitlistAPI

OPTIONS_PAYLOAD = {"appointment_types": [], "providers": [], "locations": []}

MOCK_STAFF = MagicMock(dbid=101)


def _api(secrets=None, headers=None, make_request=None):
    api = WaitlistAPI.__new__(WaitlistAPI)
    api.secrets = secrets or {}
    api.request = make_request(headers=headers or {})
    return api


class TestGetOptions:
    def test_missing_session_header_is_rejected(self, make_request):
        api = _api(make_request=make_request)

        with patch("scheduling_waitlist.routes.waitlist_api.staff_from_session", return_value=None):
            responses = api.get_options()

        assert responses[0].status_code == 401

    def test_unresolvable_staff_is_rejected_rather_than_defaulted(
        self, make_request
    ):
        # Never invent an acting user. An entry attributed to nobody is worse
        # than a refused request.
        api = _api(headers={"canvas-logged-in-user-id": "ghost"}, make_request=make_request)

        with patch("scheduling_waitlist.routes.waitlist_api.staff_from_session", return_value=None):
            responses = api.get_options()

        assert responses[0].status_code == 401
        assert "error" in responses[0].data

    def test_returns_the_option_payload_for_a_signed_in_staff_member(
        self, make_request, mock_staff
    ):
        api = _api(
            headers={"canvas-logged-in-user-id": "abc"}, make_request=make_request
        )

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=mock_staff,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.build_options",
                return_value=dict(OPTIONS_PAYLOAD),
            ),
        ):
            responses = api.get_options()

        assert responses[0].status_code == 200
        assert "appointment_types" in responses[0].data

    def test_identifies_the_caller_only_from_the_session_header(
        self, make_request, mock_staff
    ):
        api = _api(
            headers={"canvas-logged-in-user-id": "header-value"}, make_request=make_request
        )

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=mock_staff,
            ) as resolve,
            patch(
                "scheduling_waitlist.routes.waitlist_api.build_options",
                return_value=dict(OPTIONS_PAYLOAD),
            ),
        ):
            api.get_options()

        resolve.assert_called_once_with("header-value")

    def test_reports_no_blanket_management_when_no_manager_roles_configured(
        self, make_request, mock_staff
    ):
        api = _api(
            secrets={}, headers={"canvas-logged-in-user-id": "abc"}, make_request=make_request
        )

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=mock_staff,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.build_options",
                return_value=dict(OPTIONS_PAYLOAD),
            ),
        ):
            responses = api.get_options()

        assert responses[0].data["can_manage_all"] is False

    def test_reports_blanket_management_for_a_configured_manager_role(
        self, make_request, mock_staff
    ):
        api = _api(
            secrets={"WAITLIST_MANAGER_ROLE_CODES": "ADMIN"},
            headers={"canvas-logged-in-user-id": "abc"},
            make_request=make_request,
        )

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=mock_staff,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.build_options",
                return_value=dict(OPTIONS_PAYLOAD),
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all", return_value=True
            ),
        ):
            responses = api.get_options()

        assert responses[0].data["can_manage_all"] is True

    def test_includes_the_callers_own_identifier_for_ownership_checks(
        self, make_request, mock_staff
    ):
        api = _api(
            headers={"canvas-logged-in-user-id": "abc"}, make_request=make_request
        )

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=mock_staff,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.build_options",
                return_value=dict(OPTIONS_PAYLOAD),
            ),
        ):
            responses = api.get_options()

        assert responses[0].data["current_staff_dbid"] == mock_staff.dbid


def _entries_api(make_request, mock_staff, query=None, secrets=None):
    api = WaitlistAPI.__new__(WaitlistAPI)
    api.secrets = secrets or {}
    api.request = make_request(
        headers={"canvas-logged-in-user-id": "abc"}, query_params=query or {}
    )
    return api


class TestGetEntries:
    def _call(self, api, entries=(), total=0):
        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.list_entries",
                return_value=(list(entries), total),
            ) as lister,
            patch(
                "scheduling_waitlist.routes.waitlist_api.serialize_entry",
                side_effect=lambda entry, **kwargs: {"dbid": entry},
            ),
        ):
            responses = api.get_entries()
        return responses, lister

    def test_unauthenticated_caller_is_rejected(self, make_request, mock_staff):
        api = _entries_api(make_request, mock_staff)

        with patch(
            "scheduling_waitlist.routes.waitlist_api.staff_from_session", return_value=None
        ):
            responses = api.get_entries()

        assert responses[0].status_code == 401

    def test_returns_serialized_entries_with_the_unpaged_total(
        self, make_request, mock_staff
    ):
        api = _entries_api(make_request, mock_staff)

        responses, _ = self._call(api, entries=[1, 2], total=137)

        assert responses[0].data["count"] == 2
        assert responses[0].data["total"] == 137

    def test_non_numeric_limit_is_refused_with_a_named_field(
        self, make_request, mock_staff
    ):
        api = _entries_api(make_request, mock_staff, query={"limit": "lots"})

        with patch(
            "scheduling_waitlist.routes.waitlist_api.staff_from_session",
            return_value=MOCK_STAFF,
        ):
            responses = api.get_entries()

        assert responses[0].status_code == 400
        assert "limit" in responses[0].data["field_errors"]

    def test_non_numeric_offset_is_refused(self, make_request, mock_staff):
        api = _entries_api(make_request, mock_staff, query={"offset": "later"})

        with patch(
            "scheduling_waitlist.routes.waitlist_api.staff_from_session",
            return_value=MOCK_STAFF,
        ):
            responses = api.get_entries()

        assert responses[0].status_code == 400
        assert "offset" in responses[0].data["field_errors"]

    def test_unknown_sort_falls_back_instead_of_failing(self, make_request, mock_staff):
        api = _entries_api(make_request, mock_staff, query={"sort": "colour"})

        responses, _ = self._call(api)

        assert responses[0].status_code == 200
        assert responses[0].data["sort"] == "priority"

    def test_descending_sort_is_echoed_back(self, make_request, mock_staff):
        api = _entries_api(make_request, mock_staff, query={"sort": "-wait"})

        responses, _ = self._call(api)

        assert responses[0].data["sort"] == "-wait"

    def test_filters_are_passed_through_to_the_query(self, make_request, mock_staff):
        api = _entries_api(
            make_request,
            mock_staff,
            query={
                "q": "  lee  ",
                "status": "waiting",
                "appointment_type_id": "7",
                "provider_id": "any",
                "location_id": "3",
                "priority": "High",
            },
        )

        _, lister = self._call(api)

        passed = lister.call_args.kwargs
        assert passed["search"] == "lee"
        assert passed["status"] == "waiting"
        assert passed["note_type_dbid"] == "7"
        assert passed["provider_dbid"] == "any"
        assert passed["location_dbid"] == "3"
        assert passed["priority_label"] == "High"

    def test_blank_filters_are_passed_as_none_rather_than_empty_strings(
        self, make_request, mock_staff
    ):
        api = _entries_api(make_request, mock_staff, query={"appointment_type_id": ""})

        _, lister = self._call(api)

        assert lister.call_args.kwargs["note_type_dbid"] is None

    def test_oversized_page_is_capped(self, make_request, mock_staff):
        api = _entries_api(make_request, mock_staff, query={"limit": "100000"})

        responses, lister = self._call(api)

        assert lister.call_args.kwargs["limit"] == 500
        assert responses[0].data["limit"] == 500


class TestCreateEntry:
    def _post(self, api, cleaned=None, errors=None, duplicate=False):
        from scheduling_waitlist.services.entries import DuplicateEntryError

        result = MagicMock()
        result.ok = not errors
        result.errors = errors or {}
        result.cleaned = cleaned or {"patient_id": 55, "note_type_id": 7}

        create_mock = MagicMock(
            side_effect=DuplicateEntryError if duplicate else None,
            return_value=MagicMock(dbid=42),
        )

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.validate_entry",
                return_value=result,
            ),
            patch("scheduling_waitlist.routes.waitlist_api.create_entry", create_mock),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry",
                return_value=MagicMock(dbid=42),
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.serialize_entry",
                return_value={"dbid": 42},
            ),
        ):
            responses = api.create()
        return responses, create_mock

    def _api(self, make_request, body=None):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "abc"}, json_body=body or {}
        )
        return api

    def test_unauthenticated_caller_is_rejected(self, make_request):
        api = self._api(make_request)

        with patch(
            "scheduling_waitlist.routes.waitlist_api.staff_from_session", return_value=None
        ):
            responses = api.create()

        assert responses[0].status_code == 401

    def test_a_valid_submission_is_created(self, make_request):
        responses, _ = self._post(self._api(make_request))

        assert responses[0].status_code == 201

    def test_the_creator_is_taken_from_the_session_not_the_request_body(self, make_request):
        # A request body could name anyone; attribution has to come from the
        # authenticated session.
        api = self._api(make_request, body={"created_by_dbid": 999})

        _, create_mock = self._post(api)

        assert create_mock.call_args.kwargs["created_by_dbid"] == MOCK_STAFF.dbid

    def test_validation_failures_name_the_offending_fields(self, make_request):
        responses, _ = self._post(
            self._api(make_request), errors={"appointment_type_id": "Choose a service."}
        )

        assert responses[0].status_code == 400
        assert "appointment_type_id" in responses[0].data["field_errors"]

    def test_nothing_is_created_when_validation_fails(self, make_request):
        _, create_mock = self._post(self._api(make_request), errors={"priority": "bad"})

        create_mock.assert_not_called()

    def test_a_duplicate_is_reported_as_a_conflict(self, make_request):
        responses, _ = self._post(self._api(make_request), duplicate=True)

        assert responses[0].status_code == 409
        assert "already waiting" in responses[0].data["error"]


def _write_api(make_request, entry_dbid="42", body=None, query=None, secrets=None):
    api = WaitlistAPI.__new__(WaitlistAPI)
    api.secrets = secrets or {}
    api.request = make_request(
        headers={"canvas-logged-in-user-id": "abc"},
        path_params={"entry_dbid": entry_dbid},
        json_body=body or {},
        query_params=query or {},
    )
    return api


def _entry(created_by_id=101, status="waiting"):
    entry = MagicMock()
    entry.dbid = 42
    entry.created_by_id = created_by_id
    entry.status = status
    return entry


class TestWriteAuthorization:
    """Every write route resolves the entry and checks ownership the same way."""

    def _call(self, api, method, entry=None, manages_all=False):
        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry", return_value=entry
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all",
                return_value=manages_all,
            ),
        ):
            return getattr(api, method)()

    def test_a_missing_entry_is_reported_as_not_found(self, make_request):
        for method in ("update", "change_status", "remove"):
            responses = self._call(_write_api(make_request), method, entry=None)
            assert responses[0].status_code == 404, method

    def test_a_non_creator_without_a_manager_role_is_refused(self, make_request):
        for method in ("update", "change_status", "remove"):
            responses = self._call(
                _write_api(make_request), method, entry=_entry(created_by_id=999)
            )
            assert responses[0].status_code == 403, method

    def test_unauthenticated_callers_are_refused(self, make_request):
        with patch(
            "scheduling_waitlist.routes.waitlist_api.staff_from_session", return_value=None
        ):
            for method in ("update", "change_status", "remove"):
                responses = getattr(_write_api(make_request), method)()
                assert responses[0].status_code == 401, method

    def test_a_manager_may_change_an_entry_they_did_not_create(self, make_request):
        api = _write_api(make_request, body={"status": "offered"})

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry",
                return_value=_entry(created_by_id=999),
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all", return_value=True
            ),
            patch("scheduling_waitlist.routes.waitlist_api.apply_transition"),
            patch(
                "scheduling_waitlist.routes.waitlist_api.serialize_entry",
                return_value={"dbid": 42},
            ),
        ):
            responses = api.change_status()

        assert responses[0].status_code == 200


class TestChangeStatus:
    def _call(self, api, transition_error=None):
        from scheduling_waitlist.services.transitions import TransitionError

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry", return_value=_entry()
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all", return_value=False
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.apply_transition",
                side_effect=TransitionError(transition_error) if transition_error else None,
            ) as transition,
            patch(
                "scheduling_waitlist.routes.waitlist_api.serialize_entry",
                return_value={"dbid": 42},
            ),
        ):
            return api.change_status(), transition

    def test_a_valid_change_is_applied(self, make_request):
        api = _write_api(make_request, body={"status": "offered"})

        responses, transition = self._call(api)

        assert responses[0].status_code == 200
        assert transition.call_args.kwargs["to_status"] == "offered"

    def test_the_actor_comes_from_the_session(self, make_request):
        api = _write_api(make_request, body={"status": "offered"})

        _, transition = self._call(api)

        assert transition.call_args.kwargs["actor_dbid"] == MOCK_STAFF.dbid

    def test_a_refused_change_is_reported_as_a_conflict(self, make_request):
        api = _write_api(make_request, body={"status": "expired"})

        responses, _ = self._call(api, transition_error="An entry cannot move from x to y.")

        assert responses[0].status_code == 409
        assert "cannot move" in responses[0].data["error"]


class TestRemove:
    def _call(self, api):
        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry", return_value=_entry()
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all", return_value=False
            ),
            patch("scheduling_waitlist.routes.waitlist_api.apply_transition") as transition,
        ):
            return api.remove(), transition

    def test_removal_is_a_status_change_not_a_delete(self, make_request):
        # The row survives so wait-time reporting and the record of who removed
        # it are not lost.
        responses, transition = self._call(_write_api(make_request))

        assert transition.call_args.kwargs["to_status"] == "removed"
        assert responses[0].data["status"] == "removed"

    def test_a_reason_is_carried_through(self, make_request):
        api = _write_api(make_request, query={"reason": "went elsewhere"})

        _, transition = self._call(api)

        assert transition.call_args.kwargs["reason"] == "went elsewhere"


class TestUpdate:
    def test_an_edit_cannot_reassign_the_patient(self, make_request):
        # validate_entry is called with require_patient off, so a patient in the
        # body is never read.
        api = _write_api(make_request, body={"patient_id": "someone-else"})
        result = MagicMock(ok=True, errors={}, cleaned={"note": "x"})

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry", return_value=_entry()
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all", return_value=False
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.validate_entry", return_value=result
            ) as validate,
            patch("scheduling_waitlist.routes.waitlist_api.update_entry") as update,
            patch(
                "scheduling_waitlist.routes.waitlist_api.serialize_entry",
                return_value={"dbid": 42},
            ),
        ):
            responses = api.update()

        assert validate.call_args.kwargs["require_patient"] is False
        assert "patient_id" not in update.call_args.kwargs
        assert responses[0].status_code == 200

    def test_validation_failures_are_reported_per_field(self, make_request):
        api = _write_api(make_request)
        result = MagicMock(ok=False, errors={"priority": "bad"}, cleaned={})

        with (
            patch(
                "scheduling_waitlist.routes.waitlist_api.staff_from_session",
                return_value=MOCK_STAFF,
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.get_entry", return_value=_entry()
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.can_manage_all", return_value=False
            ),
            patch(
                "scheduling_waitlist.routes.waitlist_api.validate_entry", return_value=result
            ),
            patch("scheduling_waitlist.routes.waitlist_api.update_entry") as update,
        ):
            responses = api.update()

        assert responses[0].status_code == 400
        update.assert_not_called()


ROUTES = "scheduling_waitlist.routes.waitlist_api"
BANNER = "banner-effect"


class TestPatientSearch:
    """The picker behind the roster's add form.

    The chart has no add button, so this is the only way a patient gets onto the
    waitlist -- it has to be authenticated, and it has to stay narrow.
    """

    def _api(self, make_request, query=None, authenticated=True):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "abc"} if authenticated else {},
            query_params=query or {},
        )
        return api

    def test_unauthenticated_caller_is_rejected(self, make_request):
        # Patient names are the payload here, so an unauthenticated caller must
        # get nothing at all.
        api = self._api(make_request, query={"q": "love"}, authenticated=False)

        with patch(f"{ROUTES}.staff_from_session", return_value=None):
            responses = api.get_patients()

        assert responses[0].status_code == 401

    def test_no_search_runs_for_an_unauthenticated_caller(self, make_request):
        api = self._api(make_request, query={"q": "love"}, authenticated=False)

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=None),
            patch(f"{ROUTES}.search_patients") as search,
        ):
            api.get_patients()

        search.assert_not_called()

    def test_matches_are_returned_under_a_patients_key(self, make_request, mock_staff):
        api = self._api(make_request, query={"q": "love"})
        found = [{"id": "p-1", "name": "Ada Lovelace", "birth_date": "1815-12-10"}]

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=mock_staff),
            patch(f"{ROUTES}.search_patients", return_value=found),
        ):
            responses = api.get_patients()

        assert responses[0].status_code == 200
        assert responses[0].data == {"patients": found}

    def test_the_query_parameter_is_trimmed_at_the_boundary(self, make_request, mock_staff):
        # ``_query`` strips, so the service never sees a padded term. The service
        # strips again anyway -- it is also called from tests and future callers.
        api = self._api(make_request, query={"q": "  love  "})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=mock_staff),
            patch(f"{ROUTES}.search_patients", return_value=[]) as search,
        ):
            api.get_patients()

        assert search.call_args.args[0] == "love"

    def test_a_missing_query_searches_for_nothing_rather_than_erroring(
        self, make_request, mock_staff
    ):
        api = self._api(make_request)

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=mock_staff),
            patch(f"{ROUTES}.search_patients", return_value=[]) as search,
        ):
            responses = api.get_patients()

        assert responses[0].status_code == 200
        assert search.call_args.args[0] == ""

    def test_a_short_query_is_answered_with_an_empty_list_not_a_400(
        self, make_request, mock_staff
    ):
        # The picker forwards keystrokes; a 400 on the first character would be
        # noise rather than information.
        api = self._api(make_request, query={"q": "a"})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=mock_staff),
            patch(f"{ROUTES}.search_patients", return_value=[]),
        ):
            responses = api.get_patients()

        assert responses[0].status_code == 200
        assert responses[0].data == {"patients": []}


class TestWritesRefreshTheChartBanner:
    """Every write path has to keep the chart banner honest.

    The chart carries no add button, so the banner is the only chart-side signal
    that a patient is waiting -- a write that left it stale would be the whole
    feature failing quietly.
    """

    def _api(self, make_request, body=None, query=None, path="42"):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "abc"},
            json_body=body or {},
            query_params=query or {},
            path_params={"entry_dbid": path},
        )
        return api

    def test_creating_an_entry_emits_the_banner(self, make_request):
        api = self._api(make_request)
        result = MagicMock(ok=True, errors={}, cleaned={"patient_id": 55, "note_type_id": 7})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.validate_entry", return_value=result),
            patch(f"{ROUTES}.create_entry", return_value=MagicMock(dbid=42)),
            patch(f"{ROUTES}.get_entry", return_value=MagicMock(dbid=42)),
            patch(f"{ROUTES}.serialize_entry", return_value={"dbid": 42}),
            patch(f"{ROUTES}.banner_effects_for_entry", return_value=[BANNER]),
        ):
            responses = api.create()

        assert responses[0].status_code == 201
        assert BANNER in responses

    def test_editing_an_entry_emits_the_banner(self, make_request):
        # An edit can change the service, which the banner names.
        api = self._api(make_request)
        result = MagicMock(ok=True, errors={}, cleaned={"note_type_id": 9})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.get_entry", return_value=MagicMock(dbid=42, created_by_id=101)),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
            patch(f"{ROUTES}.validate_entry", return_value=result),
            patch(f"{ROUTES}.update_entry", return_value=MagicMock(dbid=42)),
            patch(f"{ROUTES}.serialize_entry", return_value={"dbid": 42}),
            patch(f"{ROUTES}.banner_effects_for_entry", return_value=[BANNER]),
        ):
            responses = api.update()

        assert BANNER in responses

    def test_a_status_change_emits_the_banner(self, make_request):
        api = self._api(make_request, body={"status": "scheduled", "reason": ""})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.get_entry", return_value=MagicMock(dbid=42, created_by_id=101)),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
            patch(f"{ROUTES}.apply_transition"),
            patch(f"{ROUTES}.serialize_entry", return_value={"dbid": 42}),
            patch(f"{ROUTES}.banner_effects_for_entry", return_value=[BANNER]),
        ):
            responses = api.change_status()

        assert BANNER in responses

    def test_removing_an_entry_emits_the_banner(self, make_request):
        api = self._api(make_request, query={"reason": "called back"})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.get_entry", return_value=MagicMock(dbid=42, created_by_id=101)),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
            patch(f"{ROUTES}.apply_transition"),
            patch(f"{ROUTES}.banner_effects_for_entry", return_value=[BANNER]),
        ):
            responses = api.remove()

        assert BANNER in responses

    def test_a_refused_write_emits_no_banner(self, make_request):
        # Nothing changed, so redrawing the banner would be a pointless write.
        from scheduling_waitlist.services.transitions import TransitionError

        api = self._api(make_request, body={"status": "nonsense"})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.get_entry", return_value=MagicMock(dbid=42, created_by_id=101)),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
            patch(f"{ROUTES}.apply_transition", side_effect=TransitionError("nope")),
            patch(f"{ROUTES}.banner_effects_for_entry", return_value=[BANNER]),
        ):
            responses = api.change_status()

        assert responses[0].status_code == 409
        assert BANNER not in responses


class TestMalformedRequestBodies:
    """A JSON body that is not an object must be refused, not crash the route.

    ``json()`` returns whatever the caller sent, so a list, a bare string, a
    number or ``null`` all reach the route. Every field reader downstream calls
    ``payload.get(...)``, which raises ``AttributeError`` on all of those -- an
    unhandled 500 for what is plainly a bad request.
    """

    NON_OBJECTS = [[], [1, 2], "text", 5, 1.5, True, None]

    @staticmethod
    def _api_with_body(make_request, body, path_params=None):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        request = make_request(
            headers={"canvas-logged-in-user-id": "s1"},
            path_params=path_params or {},
        )
        # Set directly: the fixture's ``json_body or {}`` would turn every
        # falsy body under test back into an empty object.
        request.json.return_value = body
        api.request = request
        return api

    @pytest.mark.parametrize("body", NON_OBJECTS)
    def test_create_refuses_a_body_that_is_not_an_object(self, make_request, body):
        api = self._api_with_body(make_request, body)

        with patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF):
            responses = api.create()

        assert responses[0].status_code == 400
        assert "error" in responses[0].data

    @pytest.mark.parametrize("body", NON_OBJECTS)
    def test_update_refuses_a_body_that_is_not_an_object(self, make_request, body):
        api = self._api_with_body(make_request, body, path_params={"entry_dbid": "42"})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(
                f"{ROUTES}.get_entry",
                return_value=MagicMock(dbid=42, created_by_id=101),
            ),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
        ):
            responses = api.update()

        assert responses[0].status_code == 400
        assert "error" in responses[0].data

    @pytest.mark.parametrize("body", NON_OBJECTS)
    def test_change_status_refuses_a_body_that_is_not_an_object(
        self, make_request, body
    ):
        api = self._api_with_body(make_request, body, path_params={"entry_dbid": "42"})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(
                f"{ROUTES}.get_entry",
                return_value=MagicMock(dbid=42, created_by_id=101),
            ),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
        ):
            responses = api.change_status()

        assert responses[0].status_code == 400
        assert "error" in responses[0].data

    def test_nothing_is_written_when_the_body_is_not_an_object(self, make_request):
        # The refusal must come before any attempt to create.
        api = self._api_with_body(make_request, [{"patient_id": "p1"}])

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.create_entry") as create,
            patch(f"{ROUTES}.validate_entry") as validate,
        ):
            responses = api.create()

        assert responses[0].status_code == 400
        create.assert_not_called()
        validate.assert_not_called()

    def test_an_empty_object_is_still_a_valid_body(self, make_request):
        # ``{}`` is a well-formed object; it must reach validation and be
        # refused on its missing fields, not on its shape.
        api = self._api_with_body(make_request, {})
        result = MagicMock(ok=False, errors={"patient_id": "Choose a patient."})

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.validate_entry", return_value=result) as validate,
        ):
            responses = api.create()

        validate.assert_called_once()
        assert responses[0].status_code == 400
        assert responses[0].data["field_errors"] == {"patient_id": "Choose a patient."}


class TestGetOnePatient:
    """Resolving the patient the chart button named."""

    @staticmethod
    def _api(make_request, patient_id="p-1", authed=True):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "s1"} if authed else {},
            path_params={"patient_id": patient_id},
        )
        return api

    def test_an_unauthenticated_caller_is_rejected(self, make_request):
        api = self._api(make_request, authed=False)

        with patch(f"{ROUTES}.staff_from_session", return_value=None):
            responses = api.get_patient()

        assert responses[0].status_code == 401

    def test_no_lookup_runs_for_an_unauthenticated_caller(self, make_request):
        api = self._api(make_request, authed=False)

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=None),
            patch(f"{ROUTES}.patient_by_id") as lookup,
        ):
            api.get_patient()

        lookup.assert_not_called()

    def test_a_resolved_patient_is_returned(self, make_request):
        api = self._api(make_request)
        found = {"id": "p-1", "name": "Dana Reyes", "birth_date": "1990-04-02"}

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.patient_by_id", return_value=found),
        ):
            responses = api.get_patient()

        assert responses[0].status_code == 200
        assert responses[0].data == {"patient": found}

    def test_an_unknown_patient_is_a_not_found(self, make_request):
        api = self._api(make_request, patient_id="ghost")

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.patient_by_id", return_value=None),
        ):
            responses = api.get_patient()

        assert responses[0].status_code == 404

    def test_the_key_comes_from_the_path(self, make_request):
        api = self._api(make_request, patient_id="p-9")

        with (
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.patient_by_id", return_value=None) as lookup,
        ):
            api.get_patient()

        lookup.assert_called_once_with("p-9")


class TestChartButtonsAreRefreshedAfterAWrite:
    """The chart button's label is computed at render time.

    Nothing redraws it on its own, so after a write that changes whether a
    patient is waiting, the chart keeps offering "Add to waitlist" for someone
    who is already on the list until the page is reloaded.
    """

    RELOAD = "reload-effect"

    def _patched(self, extra=None):
        patches = [
            patch(f"{ROUTES}.staff_from_session", return_value=MOCK_STAFF),
            patch(f"{ROUTES}.can_manage_all", return_value=True),
            patch(f"{ROUTES}.banner_effects_for_entry", return_value=[BANNER]),
            patch(f"{ROUTES}.serialize_entry", return_value={"dbid": 42}),
            patch(
                f"{ROUTES}.reload_chart_buttons",
                return_value=[self.RELOAD],
            ),
        ]
        return patches + (extra or [])

    def test_creating_an_entry_refreshes_the_chart_buttons(self, make_request):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "s1"},
            json_body={"patient_id": "p-1"},
        )
        entry = MagicMock(dbid=42)
        result = MagicMock(ok=True, errors={}, cleaned={"patient_id": 55})

        with contextlib.ExitStack() as stack:
            for p in self._patched(
                [
                    patch(f"{ROUTES}.validate_entry", return_value=result),
                    patch(f"{ROUTES}.create_entry", return_value=entry),
                    patch(f"{ROUTES}.get_entry", return_value=entry),
                ]
            ):
                stack.enter_context(p)
            responses = api.create()

        assert self.RELOAD in responses

    def test_a_status_change_refreshes_the_chart_buttons(self, make_request):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "s1"},
            path_params={"entry_dbid": "42"},
            json_body={"status": "scheduled"},
        )
        entry = MagicMock(dbid=42, created_by_id=101)

        with contextlib.ExitStack() as stack:
            for p in self._patched(
                [
                    patch(f"{ROUTES}.get_entry", return_value=entry),
                    patch(f"{ROUTES}.apply_transition"),
                ]
            ):
                stack.enter_context(p)
            responses = api.change_status()

        assert self.RELOAD in responses

    def test_removing_an_entry_refreshes_the_chart_buttons(self, make_request):
        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "s1"},
            path_params={"entry_dbid": "42"},
        )
        entry = MagicMock(dbid=42, created_by_id=101)

        with contextlib.ExitStack() as stack:
            for p in self._patched(
                [
                    patch(f"{ROUTES}.get_entry", return_value=entry),
                    patch(f"{ROUTES}.apply_transition"),
                ]
            ):
                stack.enter_context(p)
            responses = api.remove()

        assert self.RELOAD in responses

    def test_a_refused_write_does_not_refresh_anything(self, make_request):
        from scheduling_waitlist.services.transitions import TransitionError

        api = WaitlistAPI.__new__(WaitlistAPI)
        api.secrets = {}
        api.request = make_request(
            headers={"canvas-logged-in-user-id": "s1"},
            path_params={"entry_dbid": "42"},
            json_body={"status": "nonsense"},
        )
        entry = MagicMock(dbid=42, created_by_id=101)

        with contextlib.ExitStack() as stack:
            for p in self._patched(
                [
                    patch(f"{ROUTES}.get_entry", return_value=entry),
                    patch(
                        f"{ROUTES}.apply_transition",
                        side_effect=TransitionError("nope"),
                    ),
                ]
            ):
                stack.enter_context(p)
            responses = api.change_status()

        assert responses[0].status_code == 409
        assert self.RELOAD not in responses
