"""Tests for ordering-provider lookups."""

from lab_order_favorites.services import providers


def test_list_excludes_no_npi_inactive_and_placeholder(make_staff):
    keep = make_staff(first_name="Real", last_name="Doc", npi_number="1234567890")
    make_staff(first_name="No", last_name="Npi", npi_number="")
    make_staff(first_name="Inactive", last_name="Doc", npi_number="2222233334", active=False)
    make_staff(first_name="Placeholder", last_name="Doc", npi_number="1111155556")

    result = providers.list_ordering_providers()

    assert [p["id"] for p in result] == [str(keep.id)]
    assert result[0]["name"] == "Real Doc"
    assert result[0]["npi"] == "1234567890"


def test_list_search_matches_name_or_npi(make_staff):
    make_staff(first_name="Gregory", last_name="House", npi_number="1234567890")
    make_staff(first_name="Lisa", last_name="Cuddy", npi_number="9876543210")

    assert [p["name"] for p in providers.list_ordering_providers("house")] == ["Gregory House"]
    assert [p["name"] for p in providers.list_ordering_providers("9876543210")] == ["Lisa Cuddy"]


def test_resolve_valid_provider(make_staff):
    staff = make_staff(first_name="Real", last_name="Doc", npi_number="1234567890")
    provider, reason = providers.resolve_provider(str(staff.id))
    assert reason == ""
    assert provider is not None
    assert provider["id"] == str(staff.id)
    assert provider["npi"] == "1234567890"


def test_resolve_blank_required():
    provider, reason = providers.resolve_provider("  ")
    assert provider is None
    assert "required" in reason


def test_resolve_unknown():
    provider, reason = providers.resolve_provider("11111111-1111-1111-1111-111111111111")
    assert provider is None
    assert "not found" in reason


def test_resolve_inactive(make_staff):
    staff = make_staff(npi_number="1234567890", active=False)
    provider, reason = providers.resolve_provider(str(staff.id))
    assert provider is None
    assert "not active" in reason


def test_resolve_missing_npi(make_staff):
    staff = make_staff(npi_number="")
    provider, reason = providers.resolve_provider(str(staff.id))
    assert provider is None
    assert "valid NPI" in reason


def test_resolve_placeholder_npi(make_staff):
    staff = make_staff(npi_number="1111155556")
    provider, reason = providers.resolve_provider(str(staff.id))
    assert provider is None
    assert "valid NPI" in reason
