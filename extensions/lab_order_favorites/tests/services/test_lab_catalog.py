"""Tests for lab catalog lookups and validation against the instance."""

from lab_order_favorites.services import lab_catalog


def test_list_active_partners_excludes_inactive_and_sorts(make_partner):
    make_partner(name="Zeta Labs", active=True)
    make_partner(name="Alpha Labs", active=True)
    make_partner(name="Dead Lab", active=False)

    partners = lab_catalog.list_active_partners()

    assert [p["name"] for p in partners] == ["Alpha Labs", "Zeta Labs"]
    assert all(p["id"] for p in partners)


def test_list_tests_for_partner_excludes_blank_codes(make_partner):
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid Panel")])
    # A test with a blank order_code cannot be ordered and must be hidden.
    from canvas_sdk.v1.data.lab import LabPartnerTest

    LabPartnerTest.objects.create(lab_partner=partner, order_code="", order_name="No Code")

    tests = lab_catalog.list_tests_for_partner(str(partner.id))

    codes = sorted(t["order_code"] for t in tests)
    assert codes == ["001", "002"]


def test_list_tests_for_partner_search_matches_name_or_code(make_partner):
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid Panel")])

    by_name = lab_catalog.list_tests_for_partner(str(partner.id), search="lipid")
    by_code = lab_catalog.list_tests_for_partner(str(partner.id), search="001")

    assert [t["order_name"] for t in by_name] == ["Lipid Panel"]
    assert [t["order_code"] for t in by_code] == ["001"]


def test_resolve_partner_by_name(make_partner):
    partner = make_partner(name="Quest Diagnostics")

    resolved, reason = lab_catalog.resolve_partner("quest diagnostics")

    assert reason == ""
    assert resolved is not None
    assert resolved.id == partner.id


def test_resolve_partner_by_id(make_partner):
    partner = make_partner(name="Quest")

    resolved, reason = lab_catalog.resolve_partner(str(partner.id))

    assert reason == ""
    assert resolved is not None
    assert resolved.id == partner.id


def test_resolve_partner_ambiguous_name_is_rejected(make_partner):
    make_partner(name="Same Name")
    make_partner(name="Same Name")

    resolved, reason = lab_catalog.resolve_partner("Same Name")

    assert resolved is None
    assert "ambiguous" in reason


def test_resolve_partner_unknown_returns_reason():
    resolved, reason = lab_catalog.resolve_partner("Nonexistent Lab")

    assert resolved is None
    assert "not found" in reason


def test_resolve_partner_blank_returns_reason():
    resolved, reason = lab_catalog.resolve_partner("   ")

    assert resolved is None
    assert "required" in reason


def test_resolve_partner_valid_uuid_not_in_db():
    resolved, reason = lab_catalog.resolve_partner("11111111-1111-1111-1111-111111111111")
    assert resolved is None
    assert "not found" in reason


def test_resolve_partner_inactive_by_id_rejected(make_partner):
    partner = make_partner(name="Dormant", active=False)

    resolved, reason = lab_catalog.resolve_partner(str(partner.id))

    assert resolved is None
    assert "not active" in reason


def test_check_availability_all_valid(make_partner):
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid")])

    result = lab_catalog.check_availability(str(partner.id), ["001", "002"])

    assert result["partner_found"] is True
    assert result["partner_active"] is True
    assert result["valid"] == ["001", "002"]
    assert result["stale"] == []


def test_check_availability_splits_stale_from_valid(make_partner):
    partner = make_partner(tests=[("001", "Glucose")])

    result = lab_catalog.check_availability(str(partner.id), ["001", "999"])

    assert result["valid"] == ["001"]
    assert result["stale"] == ["999"]


def test_check_availability_is_scoped_to_selected_partner(make_partner):
    # The same code can exist on more than one lab's list. A code that only
    # exists on another partner must be stale for the selected partner.
    lab_a = make_partner(name="Lab A", tests=[("AAA", "Test A"), ("SHARED", "On both A")])
    make_partner(name="Lab B", tests=[("BBB", "Test B"), ("SHARED", "On both B")])

    result = lab_catalog.check_availability(str(lab_a.id), ["AAA", "BBB", "SHARED"])

    # AAA and SHARED belong to Lab A; BBB only exists on Lab B -> stale here.
    assert result["valid"] == ["AAA", "SHARED"]
    assert result["stale"] == ["BBB"]


def test_list_tests_only_returns_selected_partner(make_partner):
    lab_a = make_partner(name="Lab A", tests=[("AAA", "Test A")])
    make_partner(name="Lab B", tests=[("BBB", "Test B")])

    tests = lab_catalog.list_tests_for_partner(str(lab_a.id))

    assert [t["order_code"] for t in tests] == ["AAA"]


def test_check_availability_inactive_partner(make_partner):
    partner = make_partner(name="Gone", active=False, tests=[("001", "Glucose")])

    result = lab_catalog.check_availability(str(partner.id), ["001"])

    assert result["partner_found"] is True
    assert result["partner_active"] is False


def test_check_availability_missing_partner_marks_all_stale():
    result = lab_catalog.check_availability("11111111-1111-1111-1111-111111111111", ["001"])

    assert result["partner_found"] is False
    assert result["stale"] == ["001"]
    assert result["valid"] == []


def test_check_availability_non_uuid_partner_marks_all_stale():
    result = lab_catalog.check_availability("not-a-uuid", ["001", "002"])

    assert result["partner_found"] is False
    assert result["stale"] == ["001", "002"]
