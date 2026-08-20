"""Library curation gating.

The point of every test here is that no branch grants access by accident.
"""

from canvas_sdk.v1.data.staff import StaffRole

from patient_resources.constants import SECRET_ADMIN_ROLE_DOMAINS, SECRET_ADMIN_STAFF_IDS
from patient_resources.services.config import PatientResourcesConfig
from patient_resources.services.permissions import is_library_admin

DASHED = "3f040d58-0000-4000-8000-000000000001"


def _config(**secrets):
    return PatientResourcesConfig.from_secrets(secrets)


def _roles_exist(exists):
    StaffRole.objects.reset_mock()
    StaffRole.objects.filter.return_value.exists.return_value = exists


def test_unresolved_staff_is_denied():
    assert is_library_admin(None, _config()) is False


def test_administrative_role_is_allowed_by_default(mock_staff):
    _roles_exist(True)
    assert is_library_admin(mock_staff, _config()) is True
    assert StaffRole.objects.filter.call_args.kwargs == {
        "staff__dbid": mock_staff.dbid,
        "domain__in": ["ADM"],
    }


def test_staff_without_a_matching_role_is_denied(mock_staff):
    _roles_exist(False)
    assert is_library_admin(mock_staff, _config()) is False


def test_blank_domain_config_denies_without_querying(mock_staff):
    _roles_exist(True)
    assert is_library_admin(mock_staff, _config(**{SECRET_ADMIN_ROLE_DOMAINS: ""})) is False
    StaffRole.objects.filter.assert_not_called()


def test_configured_domains_are_passed_through(mock_staff):
    _roles_exist(True)
    is_library_admin(mock_staff, _config(**{SECRET_ADMIN_ROLE_DOMAINS: "adm,hyb"}))
    assert StaffRole.objects.filter.call_args.kwargs["domain__in"] == ["ADM", "HYB"]


def test_staff_without_a_dbid_is_denied(mock_staff):
    _roles_exist(True)
    mock_staff.dbid = None
    assert is_library_admin(mock_staff, _config()) is False


# --- the staff-id allowlist ------------------------------------------------


def test_listed_staff_id_is_allowed(mock_staff):
    mock_staff.id = DASHED
    config = _config(**{SECRET_ADMIN_STAFF_IDS: DASHED})
    assert is_library_admin(mock_staff, config) is True


def test_allowlist_matches_across_dashed_and_undashed_forms(mock_staff):
    mock_staff.id = DASHED.replace("-", "")
    config = _config(**{SECRET_ADMIN_STAFF_IDS: DASHED})
    assert is_library_admin(mock_staff, config) is True


def test_allowlist_replaces_the_role_rule_rather_than_adding_to_it(mock_staff):
    """An administrative-role holder who is not listed must be denied.

    A practice that names three people means those three, not those three plus
    everyone holding an administrative role.
    """
    _roles_exist(True)
    mock_staff.id = DASHED
    config = _config(**{SECRET_ADMIN_STAFF_IDS: "someone-else"})
    assert is_library_admin(mock_staff, config) is False
    StaffRole.objects.filter.assert_not_called()


def test_staff_without_an_id_is_denied_under_an_allowlist(mock_staff):
    mock_staff.id = ""
    config = _config(**{SECRET_ADMIN_STAFF_IDS: DASHED})
    assert is_library_admin(mock_staff, config) is False
