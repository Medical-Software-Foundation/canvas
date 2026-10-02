import pytest

from failed_fax_dashboard.services.access import allowed_staff_ids, is_staff_allowed


@pytest.mark.parametrize("secrets", [{}, {"FAX_DASHBOARD_STAFF_IDS": ""}, {"FAX_DASHBOARD_STAFF_IDS": " , "}])
def test_everyone_is_allowed_when_secret_is_empty_or_unset(secrets: dict[str, str]) -> None:
    tested = is_staff_allowed(secrets, "any-staff")
    assert tested is True


def test_unset_secret_allows_even_without_a_staff_id() -> None:
    tested = is_staff_allowed({}, None)
    assert tested is True


def test_listed_staff_is_allowed_ignoring_case_and_spaces() -> None:
    secrets = {"FAX_DASHBOARD_STAFF_IDS": "ABC123, def456 "}
    assert is_staff_allowed(secrets, "abc123") is True
    assert is_staff_allowed(secrets, " DEF456") is True


def test_unlisted_staff_is_denied_when_secret_is_set() -> None:
    tested = is_staff_allowed({"FAX_DASHBOARD_STAFF_IDS": "abc123"}, "zzz999")
    assert tested is False


def test_missing_staff_id_is_denied_when_secret_is_set() -> None:
    tested = is_staff_allowed({"FAX_DASHBOARD_STAFF_IDS": "abc123"}, None)
    assert tested is False


def test_allowed_staff_ids_parses_the_list() -> None:
    tested = allowed_staff_ids({"FAX_DASHBOARD_STAFF_IDS": "A, b,,C"})
    assert tested == {"a", "b", "c"}


def test_staff_ids_match_with_or_without_dashes() -> None:
    from failed_fax_dashboard.services.access import is_staff_allowed

    secrets = {"FAX_DASHBOARD_STAFF_IDS": "4150CD20-DE8A-470A-A570-A852859AC87E"}

    assert is_staff_allowed(secrets, "4150cd20de8a470aa570a852859ac87e") is True
    assert is_staff_allowed(secrets, "57f3668ea9f84f3980e772ea8451af38") is False
