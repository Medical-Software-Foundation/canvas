"""Tests for practitioner_bulk_loader.access."""

from types import SimpleNamespace
from unittest.mock import patch

from practitioner_bulk_loader.access import staff_can_load

KEY = "0123456789abcdef0123456789abcdef"
MODULE = "practitioner_bulk_loader.access"


def _roles(*roles):
    return [SimpleNamespace(internal_code=c, public_abbreviation=a, name=n) for c, a, n in roles]


def test_closed_when_nothing_is_configured():
    assert staff_can_load(KEY, {}) is False


def test_closed_without_a_signed_in_staff_member():
    assert staff_can_load(None, {"BULK_LOADER_ALLOWED_STAFF_KEYS": KEY}) is False


def test_listed_staff_key_is_allowed():
    assert staff_can_load(KEY, {"BULK_LOADER_ALLOWED_STAFF_KEYS": f"ffff, {KEY}"}) is True


def test_staff_key_matches_with_dashes_and_capitals():
    dashed = "01234567-89AB-CDEF-0123-456789ABCDEF"
    assert staff_can_load(KEY, {"BULK_LOADER_ALLOWED_STAFF_KEYS": dashed}) is True


def test_unlisted_staff_key_is_refused_without_a_role_list():
    assert staff_can_load(KEY, {"BULK_LOADER_ALLOWED_STAFF_KEYS": "f" * 32}) is False


def test_a_listed_role_allows_its_holders():
    with patch(f"{MODULE}.StaffRole") as role_model:
        role_model.objects.filter.return_value = _roles(("ADMIN", "Adm", "Practice Admin"))
        assert staff_can_load(KEY, {"BULK_LOADER_ALLOWED_ROLES": "practice admin"}) is True
        role_model.objects.filter.assert_called_once_with(staff__id=KEY)


def test_staff_without_a_listed_role_are_refused():
    with patch(f"{MODULE}.StaffRole") as role_model:
        role_model.objects.filter.return_value = _roles(("MA", "MA", "Medical Assistant"))
        assert staff_can_load(KEY, {"BULK_LOADER_ALLOWED_ROLES": "ADMIN"}) is False
