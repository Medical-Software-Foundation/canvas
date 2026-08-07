"""Identifying the acting staff member, and what they may change."""

from unittest.mock import MagicMock, patch

from scheduling_waitlist.services.permissions import (
    can_manage_all,
    can_modify_entry,
    staff_from_session,
    staff_id_candidates,
)


class TestStaffIdCandidates:
    def test_blank_header_yields_nothing_to_match(self):
        assert staff_id_candidates("") == set()
        assert staff_id_candidates(None) == set()

    def test_dashed_input_also_offers_the_undashed_form(self):
        candidates = staff_id_candidates("0f8f0f9e-1c2b-4a5d-8e7f-0a1b2c3d4e5f")

        assert "0f8f0f9e1c2b4a5d8e7f0a1b2c3d4e5f" in candidates

    def test_undashed_input_also_offers_the_dashed_form(self):
        # The naive two-form approach misses this direction entirely, which is
        # why the identifier is parsed rather than string-replaced.
        candidates = staff_id_candidates("0f8f0f9e1c2b4a5d8e7f0a1b2c3d4e5f")

        assert "0f8f0f9e-1c2b-4a5d-8e7f-0a1b2c3d4e5f" in candidates

    def test_non_uuid_input_still_offers_the_literal_value(self):
        assert staff_id_candidates("not-a-uuid") >= {"not-a-uuid", "notauuid"}


class TestStaffFromSession:
    def test_missing_header_resolves_to_nobody(self):
        assert staff_from_session(None) is None
        assert staff_from_session("") is None

    def test_looks_the_staff_member_up_by_every_candidate_form(self, mock_staff):
        with patch("scheduling_waitlist.services.permissions.Staff") as staff_model:
            staff_model.objects.filter.return_value.first.return_value = mock_staff

            result = staff_from_session("0f8f0f9e-1c2b-4a5d-8e7f-0a1b2c3d4e5f")

        assert result is mock_staff
        queried = staff_model.objects.filter.call_args.kwargs["id__in"]
        assert "0f8f0f9e1c2b4a5d8e7f0a1b2c3d4e5f" in queried

    def test_unmatched_header_resolves_to_nobody(self):
        with patch("scheduling_waitlist.services.permissions.Staff") as staff_model:
            staff_model.objects.filter.return_value.first.return_value = None

            assert staff_from_session("0f8f0f9e-1c2b-4a5d-8e7f-0a1b2c3d4e5f") is None


def _staff_with_roles(top_code="", role_codes=()):
    staff = MagicMock()
    staff.dbid = 101
    staff.top_clinical_role.internal_code = top_code
    staff.roles.all.return_value = [
        MagicMock(internal_code=code) for code in role_codes
    ]
    return staff


class TestCanManageAll:
    def test_no_configured_roles_grants_nobody(self):
        # Fails closed. This is not a lockout -- creators still manage their own
        # entries -- so an unconfigured install cannot hand everyone the ability
        # to clear the roster.
        assert can_manage_all(_staff_with_roles(top_code="ADMIN"), ()) is False

    def test_absent_staff_is_denied(self):
        assert can_manage_all(None, ("ADMIN",)) is False

    def test_top_clinical_role_grants_access(self):
        assert can_manage_all(_staff_with_roles(top_code="ADMIN"), ("ADMIN",)) is True

    def test_secondary_role_grants_access(self):
        staff = _staff_with_roles(top_code="RN", role_codes=("FRONT_DESK",))

        assert can_manage_all(staff, ("FRONT_DESK",)) is True

    def test_role_comparison_ignores_case(self):
        staff = _staff_with_roles(top_code="admin")

        assert can_manage_all(staff, ("ADMIN",)) is True

    def test_unlisted_role_is_denied(self):
        staff = _staff_with_roles(top_code="RN", role_codes=("MA",))

        assert can_manage_all(staff, ("ADMIN",)) is False

    def test_staff_without_a_roles_relation_is_denied_not_crashed(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = "RN"
        staff.roles = None

        assert can_manage_all(staff, ("ADMIN",)) is False

    def test_unusable_roles_relation_is_denied_not_crashed(self):
        staff = MagicMock()
        staff.top_clinical_role.internal_code = ""
        staff.roles.all.side_effect = TypeError("not iterable")

        assert can_manage_all(staff, ("ADMIN",)) is False


class TestCanModifyEntry:
    def test_manager_may_modify_an_entry_someone_else_created(self):
        entry = MagicMock(created_by_id=999)
        staff = MagicMock(dbid=101)

        assert can_modify_entry(entry, staff, manages_all=True) is True

    def test_creator_may_modify_their_own_entry_without_a_manager_role(self):
        entry = MagicMock(created_by_id=101)
        staff = MagicMock(dbid=101)

        assert can_modify_entry(entry, staff, manages_all=False) is True

    def test_non_creator_without_manager_role_is_denied(self):
        entry = MagicMock(created_by_id=999)
        staff = MagicMock(dbid=101)

        assert can_modify_entry(entry, staff, manages_all=False) is False

    def test_entry_with_no_recorded_creator_is_not_claimable(self):
        # Older or imported rows must not become editable by whoever asks first.
        entry = MagicMock(created_by_id=None)
        staff = MagicMock(dbid=101)

        assert can_modify_entry(entry, staff, manages_all=False) is False

    def test_absent_staff_is_denied(self):
        assert can_modify_entry(MagicMock(created_by_id=101), None, manages_all=True) is False
