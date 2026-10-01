"""Tests for provider_availability.engine.roles and schedulable-role storage."""

from unittest.mock import MagicMock, call, patch

from provider_availability.engine.roles import (
    get_available_roles,
    get_effective_schedulable_roles,
    get_schedulable_codes,
    get_schedulable_staff,
    is_schedulable_staff,
)
from provider_availability.engine.storage import (
    CACHE_TTL_SECONDS,
    SCHEDULABLE_ROLES_KEY,
    get_schedulable_roles,
    set_schedulable_roles,
)

ROLES_MODULE = "provider_availability.engine.roles"


def _role(internal_code, name="", abbreviation="", domain="", staff_id=1, role_type="ADMIN"):
    role = MagicMock()
    role.internal_code = internal_code
    role.role_type = role_type
    role.name = name
    role.public_abbreviation = abbreviation
    role.domain = domain
    role.staff_id = staff_id
    return role


def _staff(codes, role_type="ADMIN"):
    staff = MagicMock()
    staff.roles.all.return_value = [_role(c, role_type=role_type) for c in codes]
    return staff


class TestSchedulableRolesStorage:
    def test_unset_reads_as_not_configured(self, patch_cache):
        assert get_schedulable_roles() is None

    def test_set_then_get_roundtrips(self, patch_cache):
        set_schedulable_roles(["CC", "MD"])
        assert get_schedulable_roles() == ["CC", "MD"]
        assert patch_cache._store[SCHEDULABLE_ROLES_KEY] == ["CC", "MD"]

    def test_set_uses_cache_ttl(self, patch_cache):
        set_schedulable_roles(["CC"])
        assert patch_cache.set.mock_calls == [
            call(SCHEDULABLE_ROLES_KEY, ["CC"], timeout_seconds=CACHE_TTL_SECONDS)
        ]

    def test_empty_list_is_preserved_not_defaulted(self, patch_cache):
        # An explicit empty list must NOT fall back to the provider default.
        set_schedulable_roles([])
        assert get_schedulable_roles() == []


class TestGetSchedulableCodes:
    def test_normalizes_and_drops_blanks(self):
        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=["md", " DO ", "", "np"]):
            assert get_schedulable_codes() == {"MD", "DO", "NP"}

    def test_empty_config(self):
        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=[]):
            assert get_schedulable_codes() == set()


class TestIsSchedulableStaff:
    def test_matches_configured_code(self):
        assert is_schedulable_staff(_staff(["MD"]), {"MD"}) is True

    def test_match_is_case_insensitive(self):
        assert is_schedulable_staff(_staff(["md"]), {"MD"}) is True

    def test_matches_non_clinical_role(self):
        # Care Coordinator — the whole point of the feature.
        assert is_schedulable_staff(_staff(["CC"]), {"CC"}) is True

    def test_matches_when_any_of_several_roles_qualifies(self):
        assert is_schedulable_staff(_staff(["AD", "CC"]), {"CC"}) is True

    def test_no_match_returns_false(self):
        assert is_schedulable_staff(_staff(["RN"]), {"MD", "DO"}) is False

    def test_blank_internal_code_never_matches(self):
        assert is_schedulable_staff(_staff([""]), set()) is False


class TestGetSchedulableStaff:
    def test_filters_active_staff_by_configured_codes(self):
        provider = _staff(["MD"])
        admin = _staff(["AD"])
        coordinator = _staff(["CC"])

        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=["MD", "CC"]), \
             patch(f"{ROLES_MODULE}.Staff.objects") as mock_staff:
            mock_staff.filter.return_value.prefetch_related.return_value = [provider, admin, coordinator]

            result = get_schedulable_staff()

            assert mock_staff.mock_calls == [
                call.filter(active=True),
                call.filter().prefetch_related("roles"),
            ]
            assert result == [provider, coordinator]

    def test_unconfigured_schedules_every_provider_role_type(self):
        """Before a practice saves roles, the plugin keeps its original rule:
        anyone holding a Provider-type role, whatever the role's code."""
        therapist = _staff(["LCSW"], role_type="PROVIDER")
        physician = _staff(["MD"], role_type="PROVIDER")
        admin = _staff(["AD"])

        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=None), \
             patch(f"{ROLES_MODULE}.Staff.objects") as mock_staff:
            mock_staff.filter.return_value.prefetch_related.return_value = [therapist, physician, admin]

            assert get_schedulable_staff() == [therapist, physician]

    def test_configured_roles_matching_nobody_fall_back_to_provider_role_type(self):
        physician = _staff(["MD"], role_type="PROVIDER")
        admin = _staff(["AD"])

        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=["CC"]), \
             patch(f"{ROLES_MODULE}.Staff.objects") as mock_staff:
            mock_staff.filter.return_value.prefetch_related.return_value = [physician, admin]

            assert get_schedulable_staff() == [physician]


class TestEffectiveSchedulableRoles:
    def test_configured_list_is_shown_as_is(self):
        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=["CC", "MD"]), \
             patch(f"{ROLES_MODULE}.StaffRole.objects") as mock_roles:
            assert get_effective_schedulable_roles() == ["CC", "MD"]
            assert mock_roles.mock_calls == []

    def test_unconfigured_shows_the_provider_type_codes_in_use(self):
        with patch(f"{ROLES_MODULE}.get_schedulable_roles", return_value=None), \
             patch(f"{ROLES_MODULE}.StaffRole.objects") as mock_roles:
            mock_roles.filter.return_value = [_role("np"), _role("LCSW"), _role("NP"), _role("")]

            assert get_effective_schedulable_roles() == ["LCSW", "NP"]
            assert mock_roles.mock_calls == [call.filter(staff__active=True, role_type="PROVIDER")]


class TestGetAvailableRoles:
    def test_aggregates_by_code_with_distinct_staff_counts(self):
        roles = [
            _role("MD", "Physician", "MD", "CLI", staff_id=1),
            _role("MD", "Physician", "MD", "CLI", staff_id=2),
            _role("CC", "Care Coordinator", "", "HYB", staff_id=3),
        ]
        with patch(f"{ROLES_MODULE}.StaffRole.objects") as mock_role:
            mock_role.filter.return_value = roles

            result = get_available_roles()

            assert mock_role.mock_calls == [call.filter(staff__active=True)]
            # Sorted by descending staff_count, then code: MD (2) before CC (1)
            assert result == [
                {"code": "MD", "name": "Physician", "abbreviation": "MD",
                 "domain": "CLI", "staff_count": 2},
                {"code": "CC", "name": "Care Coordinator", "abbreviation": "",
                 "domain": "HYB", "staff_count": 1},
            ]

    def test_skips_blank_internal_codes(self):
        roles = [_role("", "Mystery", "", "ADM", staff_id=1)]
        with patch(f"{ROLES_MODULE}.StaffRole.objects") as mock_role:
            mock_role.filter.return_value = roles

            assert get_available_roles() == []

    def test_normalizes_code_to_upper(self):
        roles = [_role("cc", "Care Coordinator", "", "HYB", staff_id=7)]
        with patch(f"{ROLES_MODULE}.StaffRole.objects") as mock_role:
            mock_role.filter.return_value = roles

            result = get_available_roles()

            assert result[0]["code"] == "CC"
