"""Lab catalog, provider list, and lookup matching used by the editor and import."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from order_favorites.services import catalog, lookups
from order_favorites.services.notes import eligible_note, eligible_note_by_dbid, note_label
from tests.conftest import make_api, reply

NPI = "1234567893"


def test_partner_tests_search_by_name_or_code_and_skip_blank_codes(make_partner: Any) -> None:
    partner = make_partner(tests=[("001", "Comprehensive panel"), ("002", "TSH"), ("", "Not orderable")])
    assert [t["code"] for t in catalog.partner_tests(str(partner.id))] == ["001", "002"]
    assert catalog.partner_tests(str(partner.id), "tsh") == [{"code": "002", "name": "TSH"}]
    assert catalog.partner_tests(str(partner.id), "001") == [{"code": "001", "name": "Comprehensive panel"}]
    assert catalog.partner_tests("not-a-uuid") == []


def test_partner_tests_match_every_word_in_name_code_or_keywords_and_stop_at_the_limit(make_partner: Any) -> None:
    from canvas_sdk.v1.data import LabPartnerTest

    partner = make_partner(tests=[("001", "Comprehensive panel"), ("002", "Lipid panel"), ("003", "TSH")])
    LabPartnerTest.objects.filter(order_code="003").update(keywords="thyroid screen")
    assert [t["code"] for t in catalog.partner_tests(str(partner.id), "panel 002")] == ["002"]
    assert [t["code"] for t in catalog.partner_tests(str(partner.id), "thyroid")] == ["003"]
    assert catalog.partner_tests(str(partner.id), "panel tsh") == []
    assert len(catalog.partner_tests(str(partner.id), "panel", limit=1)) == 1


def test_resolve_tests_refuses_a_name_two_tests_share_and_ignores_blanks(make_partner: Any) -> None:
    partner = make_partner(tests=[("001", "Panel"), ("002", "Panel"), ("003", "TSH")])
    found, missing = catalog.resolve_tests(str(partner.id), ["panel", " ", "tsh"])
    assert found == [{"code": "003", "name": "TSH"}]
    assert missing == ["panel"]
    assert catalog.resolve_tests(str(partner.id), []) == ([], [])


def test_resolve_partner_by_name_or_id_and_never_guesses(make_partner: Any) -> None:
    one = make_partner(name="Labcorp")
    make_partner(name="Twin")
    make_partner(name="Twin")
    inactive = make_partner(name="Old Lab", active=False)
    assert catalog.resolve_partner("labcorp")[0] == one
    assert catalog.resolve_partner(str(one.id))[0] == one
    assert catalog.resolve_partner("Twin") == (None, "more than one lab partner is named Twin")
    assert catalog.resolve_partner(str(inactive.id)) == (None, "Old Lab is not an active lab partner")
    assert catalog.resolve_partner("Nope") == (None, "no active lab partner is named Nope")
    assert catalog.resolve_partner("") == (None, "the lab partner is missing")


def test_resolve_tests_by_code_or_exact_name(make_partner: Any) -> None:
    partner = make_partner(tests=[("001", "CMP"), ("002", "TSH")])
    found, missing = catalog.resolve_tests(str(partner.id), ["cmp", "002", "001", "Free T4"])
    assert found == [{"code": "001", "name": "CMP"}, {"code": "002", "name": "TSH"}]
    assert missing == ["Free T4"]


def test_ordering_providers_leave_out_placeholder_and_missing_npis(make_staff: Any) -> None:
    make_staff(first="Real", last="Doc", npi=NPI)
    make_staff(first="Place", last="Holder", npi="1111155556")
    make_staff(first="No", last="Npi")
    make_staff(first="Gone", last="Doc", npi=NPI, active=False)
    assert [p["name"] for p in catalog.ordering_providers()] == ["Real Doc"]
    assert catalog.ordering_providers("zzz") == []


def test_lab_lookups_through_the_api(make_staff: Any, make_partner: Any) -> None:
    me = make_staff(first="Real", last="Doc", npi=NPI)
    partner = make_partner(tests=[("001", "CMP")])
    _s, body = reply(make_api(me).lab_partners())
    assert body["results"] == [{"id": str(partner.id), "name": "Generic Lab"}]
    _s, body = reply(make_api(me, query={"partner_id": str(partner.id), "q": "cm"}).lab_tests())
    assert body["results"] == [{"code": "001", "name": "CMP"}]
    _s, body = reply(make_api(me).providers())
    assert [p["name"] for p in body["results"]] == ["Real Doc"]


def test_searches_need_two_letters(make_staff: Any) -> None:
    me = make_staff()
    for route in ("medications", "pharmacies", "diagnoses"):
        _s, body = reply(getattr(make_api(me, query={"q": "a"}), route)())
        assert body == {"results": []}


def test_pharmacy_search_shapes_the_address() -> None:
    rows = [{"ncpdp_id": 55, "organization_name": "Corner Pharmacy", "address_line_1": "1 Main St", "address_line_2": "", "city": "Town", "state": "CA", "zip_code": "90000"}]
    with patch.object(lookups.pharmacy_http, "search_pharmacies", return_value=rows):
        assert lookups.search_pharmacies("corner") == [{"ncpdp_id": "55", "name": "Corner Pharmacy", "address": "1 Main St, Town, CA 90000"}]


def test_find_medication_needs_an_exact_single_match() -> None:
    meds = [{"fdb_code": "1", "name": "drug 10 mg tablet", "units": []}, {"fdb_code": "2", "name": "drug 20 mg tablet", "units": []}]
    with patch.object(lookups, "search_medications", return_value=meds):
        by_name, _ = lookups.find_medication("Drug 10 mg tablet")
        by_code, _ = lookups.find_medication("2")
        assert by_name is not None and by_name["fdb_code"] == "1"
        assert by_code is not None and by_code["fdb_code"] == "2"
        assert lookups.find_medication("drug")[0] is None
    assert lookups.find_medication("") == (None, "the medication is missing")


def test_find_diagnosis_matches_the_exact_code() -> None:
    payload = {"results": [{"icd10_code": "E559", "icd10_text": "Vitamin D deficiency, unspecified"}, {"icd10_code": "E5590", "icd10_text": "other"}]}
    with patch.object(lookups.science_http, "get_json", return_value=SimpleNamespace(json=lambda: payload)):
        assert lookups.find_diagnosis("E55.9") == {"code": "E559", "text": "Vitamin D deficiency, unspecified"}
        assert lookups.find_diagnosis("E55.91") is None
    assert lookups.find_diagnosis("vitamin") is None


def test_note_lookup_tolerates_bad_ids(make_note: Any, make_staff: Any) -> None:
    assert eligible_note("not-a-uuid") is None
    assert eligible_note(None) is None
    assert eligible_note_by_dbid("abc") is None
    provider = make_staff(first="Dana", last="Lee")
    note = make_note(provider=provider, title="")
    label = note_label(eligible_note(str(note.id)))
    assert (label["title"], label["provider"]) == ("Encounter", "Dana Lee")
