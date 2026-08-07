"""The staff-authenticated waitlist endpoints."""

from unittest.mock import MagicMock, patch

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
