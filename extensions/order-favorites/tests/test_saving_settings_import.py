"""What a favorite must contain to save, the practice settings, import, and the lookup shapes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from requests import RequestException

from order_favorites.models import Favorite, FavoritesAdmin
from order_favorites.services import lookups
from order_favorites.services.favorites import Invalid, clean_favorite
from order_favorites.services.importer import check_csv, split_line
from tests.conftest import make_api, reply
from tests.helpers import favorite, lab_details, rx_body

NPI = "1234567893"


@pytest.fixture
def admin(make_staff: Any) -> Any:
    staff = make_staff(first="Pat", last="Admin")
    FavoritesAdmin.objects.create(staff_id=staff.dbid)
    return staff


# ---------- saving ----------

@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": ""}, "Name is required."),
        ({"fdb_code": ""}, "Medication is required."),
        ({"fdb_code": "abc"}, "Select the medication from the search list."),
        ({"days_supply": "0"}, "Days supply must be between 1 and 365."),
        ({"quantity": "0"}, "Quantity must be more than 0."),
        ({"quantity": "lots"}, "Quantity must be a number."),
        ({"refills": "100"}, "Refills must be between 0 and 99."),
        ({"ncpdp_quantity_qualifier_code": ""}, "Select the unit from the list."),
    ],
)
def test_prescription_values_that_are_filled_in_must_be_valid(change: dict[str, Any], message: str) -> None:
    with pytest.raises(Invalid, match=message):
        clean_favorite(rx_body(**change))


def test_prescription_needs_only_a_name_and_a_medication() -> None:
    body = rx_body(sig="", days_supply="", quantity="", unit="", representative_ndc="", ncpdp_quantity_qualifier_code="", refills="")
    _kind, _name, details = clean_favorite(body)
    assert (details["sig"], details["days_supply"], details["quantity"], details["refills"]) == ("", None, None, None)
    assert (details["unit"], details["representative_ndc"]) == ("", "")


def test_prescription_saves_the_order_fields_only() -> None:
    kind, name, details = clean_favorite(rx_body(quantity="30.0", junk="x"))
    assert (kind, name) == ("rx", "Amoxicillin 500 mg · 10 day")
    assert details["quantity"] == "30"
    assert "junk" not in details
    assert details["pharmacy_name"] == ""


def test_lab_test_the_partner_doesnt_offer_cant_be_saved(make_partner: Any) -> None:
    partner = make_partner(tests=[("001", "CMP")])
    body = {"kind": "lab", "name": "Panel", **lab_details(partner, ["001", "999"])}
    with pytest.raises(Invalid, match="Generic Lab doesn't offer 999"):
        clean_favorite(body)


def test_lab_needs_an_active_partner_and_a_test(make_partner: Any) -> None:
    inactive = make_partner(active=False, tests=[("001", "CMP")])
    with pytest.raises(Invalid, match="Select an active lab partner."):
        clean_favorite({"kind": "lab", "name": "x", **lab_details(inactive, ["001"])})
    active = make_partner(name="Other", tests=[("001", "CMP")])
    with pytest.raises(Invalid, match="Add at least one test."):
        clean_favorite({"kind": "lab", "name": "x", **lab_details(active, [])})


def test_lab_diagnoses_must_be_icd10_codes_and_are_stored_without_dots(make_partner: Any) -> None:
    partner = make_partner(tests=[("001", "CMP")])
    body = {"kind": "lab", "name": "x", **lab_details(partner, ["001"], diagnoses=[{"code": "E11.9", "text": "T2DM"}, {"code": "e119", "text": "dup"}])}
    _kind, _name, details = clean_favorite(body)
    assert details["diagnoses"] == [{"code": "E119", "text": "T2DM"}]
    body["diagnoses"] = [{"code": "diabetes", "text": ""}]
    with pytest.raises(Invalid, match="isn't an ICD-10 code"):
        clean_favorite(body)


def test_lab_ordering_provider_must_have_a_usable_npi(make_partner: Any, make_staff: Any) -> None:
    partner = make_partner(tests=[("001", "CMP")])
    placeholder = make_staff(npi="1111155556")
    good = make_staff(first="Real", last="Doc", npi=NPI)
    with pytest.raises(Invalid, match="must be active staff with an NPI"):
        clean_favorite({"kind": "lab", "name": "x", **lab_details(partner, ["001"], ordering_provider_id=str(placeholder.id))})
    _k, _n, details = clean_favorite({"kind": "lab", "name": "x", **lab_details(partner, ["001"], ordering_provider_id=str(good.id))})
    assert details["ordering_provider_name"] == "Real Doc"


def test_admin_saves_practice_favorites_and_lists_stale_ones(admin: Any, make_partner: Any) -> None:
    partner = make_partner(tests=[("001", "CMP"), ("002", "TSH")])
    status, body = reply(make_api(admin, body={"kind": "lab", "name": "Thyroid", **lab_details(partner, ["002"])}).admin_create())
    assert status == 201
    assert body["favorite"]["shared"] is True
    from canvas_sdk.v1.data.lab import LabPartnerTest

    LabPartnerTest.objects.filter(order_code="002").delete()
    _s, data = reply(make_api(admin).admin_data())
    assert data["favorites"][0]["stale"] == ["002"]


def test_admin_can_change_and_delete_only_practice_favorites(admin: Any) -> None:
    practice = favorite(admin, shared=True, name="Practice")
    personal = favorite(admin, name="Personal")
    status, body = reply(make_api(admin, path={"favorite_id": str(practice.dbid)}, body=rx_body(name="Renamed")).admin_update())
    assert (status, body["favorite"]["name"]) == (200, "Renamed")
    status, _ = reply(make_api(admin, path={"favorite_id": str(personal.dbid)}).admin_delete())
    assert status == 404
    status, _ = reply(make_api(admin, path={"favorite_id": str(practice.dbid)}).admin_delete())
    assert status == 200
    assert list(Favorite.objects.values_list("name", flat=True)) == ["Personal"]


# ---------- settings ----------

def test_at_least_one_order_type_stays_enabled(admin: Any, make_note: Any) -> None:
    status, body = reply(make_api(admin, body={"rx_enabled": False}).admin_settings())
    assert (status, body["title"]) == (200, "Lab Order Favorites")
    status, body = reply(make_api(admin, body={"lab_enabled": False}).admin_settings())
    assert (status, body["error"]) == (400, "At least one of prescriptions or labs must stay on.")


def test_disabled_order_type_disappears_from_the_panel(admin: Any, make_note: Any) -> None:
    favorite(admin, shared=True, name="Amox")
    reply(make_api(admin, body={"rx_enabled": False}).admin_settings())
    _s, body = reply(make_api(admin, query={"note_id": str(make_note().id)}).panel_data())
    assert body["kinds"] == ["lab"]
    assert body["title"] == "Lab Order Favorites"
    assert body["favorites"] == []


def test_admin_staff_search_leaves_out_existing_admins(admin: Any, make_staff: Any) -> None:
    make_staff(first="Pat", last="Other", email="pat.other@example.org")
    _s, body = reply(make_api(admin, query={"q": "pat"}).admin_staff())
    assert [r["name"] for r in body["results"]] == ["Pat Other"]


def test_adding_an_admin(admin: Any, make_staff: Any) -> None:
    new = make_staff(first="New", email="new@example.org")
    _s, body = reply(make_api(admin, body={"staff_id": str(new.id)}).admin_add())
    assert {a["name"] for a in body["admins"]} == {"Pat Admin", "New Provider"}


# ---------- import ----------

AMOX = {"fdb_code": "123456", "name": "amoxicillin 500 mg capsule", "units": [{"description": "capsule", "representative_ndc": "1", "ncpdp_quantity_qualifier_code": "C48480"}]}


def test_split_line_handles_quotes_and_commas() -> None:
    assert split_line('rx,"Amox, 10 day","a|b"') == ["rx", "Amox, 10 day", "a|b"]
    assert split_line('lab,"Say ""hi""",x') == ["lab", 'Say "hi"', "x"]


def test_check_csv_says_which_test_names_are_shared_and_which_match_nothing(make_partner: Any) -> None:
    make_partner(tests=[("L1", "Lipid panel (refl)"), ("L2", "Lipid panel (refl)"), ("A1C", "Hemoglobin A1c")])
    text = "type,name,details\nlab,Two problems,Generic Lab|lipid panel (refl);hemoglobn a1c||no|\n"
    [row] = check_csv(text)["rows"]
    assert not row["ok"]
    assert row["reason"] == (
        "Generic Lab has more than one test named lipid panel (refl). Use its order code instead. "
        "Generic Lab has no test with the code or name hemoglobn a1c."
    )


def test_check_csv_reports_each_row(make_partner: Any) -> None:
    make_partner(tests=[("VITD", "Vitamin D 25-OH")])
    text = (
        "type,name,details\n"
        "rx,Amox,amoxicillin 500 mg capsule|Take 1 capsule three times daily|10|30|capsule|0\n"
        "lab,Vitamin D check,Generic Lab|Vitamin D 25-OH|E55.9|no|\n"
        "lab,Kidney check,Generic Lab|NOT-A-TEST\n"
        "rx,Bad row,\n"
        "xx,Wrong type,whatever\n"
    )
    with (
        patch("order_favorites.services.importer.find_medication", return_value=(AMOX, "")),
        patch("order_favorites.services.importer.find_diagnosis", return_value={"code": "E559", "text": "Vitamin D deficiency"}),
    ):
        result = check_csv(text)
    rows = {r["row"]: r for r in result["rows"]}
    assert rows[2]["ok"] and rows[2]["favorite"]["details"]["representative_ndc"] == "1"
    assert rows[3]["ok"] and rows[3]["summary"] == "Generic Lab · 1 test · E55.9"
    assert rows[4]["reason"] == "Generic Lab has no test with the code or name NOT-A-TEST."
    assert rows[5]["reason"] == "The medication is missing."
    assert rows[6]["reason"] == "Type must be rx or lab."


def test_check_csv_refuses_a_wrong_header_and_a_unit_the_drug_doesnt_use() -> None:
    assert check_csv("name,type\nx,y")["error"] == "The first line must be the header: type,name,details"
    with patch("order_favorites.services.importer.find_medication", return_value=(AMOX, "")):
        result = check_csv("type,name,details\nrx,Amox,amoxicillin 500 mg capsule|sig|10|30|tablet|0\n")
    assert result["rows"][0]["reason"] == 'amoxicillin 500 mg capsule isn\'t dispensed by "tablet". Units offered: capsule.'


def test_import_accepts_a_prescription_with_only_the_medication() -> None:
    with patch("order_favorites.services.importer.find_medication", return_value=(AMOX, "")):
        result = check_csv("type,name,details\nrx,Amox,amoxicillin 500 mg capsule\n")
    [row] = result["rows"]
    assert row["ok"] and row["summary"] == "amoxicillin 500 mg capsule"
    assert row["favorite"]["details"]["refills"] is None


def test_import_saves_good_rows_as_practice_favorites(admin: Any) -> None:
    text = "type,name,details\nrx,Amox,amoxicillin 500 mg capsule|Take 1 capsule|10|30|capsules|0\nrx,Bad,\n"
    with patch("order_favorites.services.importer.find_medication", return_value=(AMOX, "")):
        status, body = reply(make_api(admin, body={"csv": text}).admin_import())
    assert (status, body) == (200, {"imported": 1, "skipped": 1})
    saved = Favorite.objects.get()
    assert (saved.shared, saved.owner_id, saved.details["unit"]) == (True, admin.dbid, "capsule")


# ---------- lookups ----------

def test_icd10_display() -> None:
    assert lookups.icd10_display("E119") == "E11.9"
    assert lookups.icd10_display("I10") == "I10"


def test_diagnosis_search_keeps_one_row_per_code() -> None:
    payload = {"results": [{"icd10_code": "E119", "icd10_text": "Type 2 diabetes mellitus without complications"}, {"icd10_code": "E119", "icd10_text": "dup"}, {"icd10_code": "E1122", "icd10_text": "With CKD"}]}
    with patch.object(lookups.science_http, "get_json", return_value=SimpleNamespace(json=lambda: payload)):
        assert lookups.search_diagnoses("type 2") == [
            {"code": "E119", "text": "Type 2 diabetes mellitus without complications"},
            {"code": "E1122", "text": "With CKD"},
        ]


def test_lookup_failure_is_a_503_not_an_empty_list(make_staff: Any) -> None:
    with patch.object(lookups.science_http, "get_json", side_effect=RequestException("down")):
        status, _ = reply(make_api(make_staff(), query={"q": "diabetes"}).diagnoses())
    assert status == 503


def test_medication_search_keeps_only_units_that_can_be_prescribed() -> None:
    payload = {"results": [{"med_medication_id": 9, "med_medication_description": "drug", "clinical_quantities": [
        {"representative_ndc": "1", "erx_ncpdp_script_quantity_qualifier_code": "C1", "clinical_quantity_description": "tablet"},
        {"representative_ndc": "", "erx_ncpdp_script_quantity_qualifier_code": "C2", "clinical_quantity_description": "broken"},
    ]}]}
    with patch.object(lookups.ontologies_http, "get_json", return_value=SimpleNamespace(json=lambda: payload)):
        [med] = lookups.search_medications("drug")
    assert med["fdb_code"] == "9"
    assert [u["description"] for u in med["units"]] == ["tablet"]
