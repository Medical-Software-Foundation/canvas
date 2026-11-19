"""Imaging favorites: the study must be what Canvas puts in the Image field for its code, on save and
again on every add, and an imaging order is never staged blank."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from requests import RequestException

from order_favorites.handlers.api import _title
from order_favorites.models import Favorite, FavoritesAdmin
from order_favorites.services import lookups
from order_favorites.services.access import set_setting
from order_favorites.services.favorites import Invalid, clean_favorite, stale_map
from order_favorites.services.importer import check_csv
from tests.conftest import make_api, reply
from tests.helpers import effects_of, favorite

NPI = "1234567893"
CHEST = {"name": "XR chest 2 views", "code_system": "CPT", "code": "71046"}
OTHER = {"name": "XR chest 1 view", "code_system": "CPT", "code": "71045"}
CENTER = {"first_name": "", "last_name": "", "specialty": "Radiology", "practice_name": "Main Imaging", "business_fax": "5550001111", "business_phone": "", "business_address": "1 Main St", "notes": ""}


def science(studies: list[dict[str, Any]] | None = None, centers: list[dict[str, Any]] | None = None, status: int = 200) -> Any:
    """A stand-in for science_http.get_json that answers imaging and contact searches, recording each path."""
    paths: list[str] = []

    def get_json(path: str) -> SimpleNamespace:
        paths.append(path)
        rows = centers if path.startswith("/contacts/") else studies
        return SimpleNamespace(status_code=status, json=lambda: {"results": rows or []})

    get_json.paths = paths  # type: ignore[attr-defined]
    return get_json


@pytest.fixture
def chest_first() -> Iterator[Any]:
    """Science answers every imaging search with the chest x-ray first."""
    fake = science([CHEST, OTHER])
    with patch.object(lookups.science_http, "get_json", side_effect=fake):
        yield fake


@pytest.fixture
def imaging_on() -> None:
    set_setting("imaging_enabled", True)


def imaging_body(**kw: Any) -> dict[str, Any]:
    return {
        "kind": "imaging",
        "name": "Chest x-ray",
        "image_code": "71046",
        "image_code_system": "CPT",
        "image_name": "XR chest 2 views",
        "diagnoses": [],
        "priority": "",
        "additional_details": "",
        "comment": "",
        "ordering_provider_id": "",
        "imaging_center": None,
        **kw,
    }


def imaging_details(**kw: Any) -> dict[str, Any]:
    details = {k: v for k, v in imaging_body(**kw).items() if k not in ("kind", "name")}
    details.setdefault("ordering_provider_name", "")
    return details


def add(staff: Any, note: Any, ids: list[int]) -> tuple[int, dict[str, Any], list[Any]]:
    results = make_api(staff, body={"favorite_ids": ids}, path={"note_id": str(note.id)}).add_to_note()
    status, body = reply(results)
    return status, body, results


# ---------- saving ----------

def test_imaging_favorite_saves_the_study_canvas_will_pick(chest_first: Any, make_staff: Any) -> None:
    doc = make_staff(first="Real", last="Doc", npi=NPI)
    body = imaging_body(
        image_name="typed by hand",
        diagnoses=[{"code": "R05.9", "text": "Cough"}, {"code": "r059", "text": "dup"}],
        priority="stat",
        additional_details="Rule out pneumonia",
        comment="Call with results",
        ordering_provider_id=str(doc.id),
        imaging_center=CENTER,
    )
    kind, name, details = clean_favorite(body)
    assert (kind, name) == ("imaging", "Chest x-ray")
    assert details == {
        "image_code": "71046",
        "image_name": "XR chest 2 views",
        "image_code_system": "CPT",
        "diagnoses": [{"code": "R059", "text": "Cough"}],
        "priority": "STAT",
        "additional_details": "Rule out pneumonia",
        "comment": "Call with results",
        "ordering_provider_id": str(doc.id),
        "ordering_provider_name": "Real Doc",
        "imaging_center": CENTER,
    }
    assert chest_first.paths == ["/parse-templates/imaging-reports/?query=71046&limit=25"]


def test_practice_imaging_favorite_keeps_no_ordering_provider(chest_first: Any, make_staff: Any) -> None:
    doc = make_staff(npi=NPI)
    _k, _n, details = clean_favorite(imaging_body(ordering_provider_id=str(doc.id)), shared=True)
    assert (details["ordering_provider_id"], details["ordering_provider_name"]) == ("", "")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"image_code": ""}, "Study is required."),
        ({"priority": "soon"}, "Priority must be Routine, Urgent, or STAT."),
        ({"diagnoses": [{"code": "cough"}]}, "Select indications from the search list."),
        ({"diagnoses": [{"code": f"R0{i}"} for i in range(13)]}, "An imaging favorite can have at most 12 indications."),
        ({"additional_details": "x" * 1025}, "Additional details can be at most 1024 characters."),
        ({"comment": "x" * 1025}, "Comment can be at most 1024 characters."),
        ({"imaging_center": "Main Imaging"}, "Select the imaging center from the search list."),
        ({"imaging_center": {**CENTER, "practice_name": ""}}, "The imaging center needs a practice name or a last name. Select it from the search list."),
        ({"diagnoses": 5}, "Select indications from the search list."),
        ({"diagnoses": {"code": "R059"}}, "Select indications from the search list."),
        ({"imaging_center": {**CENTER, "notes": "x" * 513}}, "Imaging center notes can be at most 512 characters."),
        ({"ordering_provider_id": "not-staff"}, "must be active staff with an NPI"),
    ],
)
def test_imaging_values_must_be_valid(chest_first: Any, change: dict[str, Any], message: str) -> None:
    with pytest.raises(Invalid, match=message):
        clean_favorite(imaging_body(**change))


@pytest.mark.parametrize(
    ("studies", "body"),
    [
        ([OTHER, CHEST], imaging_body()),  # Canvas would pick the one-view study
        ([], imaging_body()),  # Canvas would leave the Image field blank
        ([CHEST], imaging_body(image_code_system="SNOMED")),  # same code, another code system
        ([{**CHEST, "name": ""}], imaging_body()),
    ],
)
def test_study_canvas_wouldnt_pick_first_cant_be_saved(studies: list[dict[str, Any]], body: dict[str, Any]) -> None:
    with patch.object(lookups.science_http, "get_json", side_effect=science(studies)), pytest.raises(Invalid, match="doesn't find XR chest 2 views first"):
        clean_favorite(body)


@pytest.mark.parametrize("failure", [RequestException("down"), None])
def test_save_is_refused_when_science_doesnt_answer(failure: Exception | None) -> None:
    side = failure if failure is not None else science([CHEST], status=502)
    with patch.object(lookups.science_http, "get_json", side_effect=side), pytest.raises(lookups.LookupFailed):
        clean_favorite(imaging_body())


@pytest.mark.parametrize("route", ["create_favorite", "update_favorite", "admin_create", "admin_update"])
def test_saving_while_science_is_down_answers_503_not_400(route: str, imaging_on: None, make_staff: Any) -> None:
    me = make_staff()
    FavoritesAdmin.objects.create(staff_id=me.dbid)
    existing = favorite(me, kind="imaging", name="Chest", details=imaging_details(), shared=route == "admin_update")
    api = make_api(me, body=imaging_body(), path={"favorite_id": str(existing.dbid)})
    with patch.object(lookups.science_http, "get_json", side_effect=RequestException("down")):
        status, body = reply(getattr(api, route)())
    assert status == 503
    assert "imaging search didn't answer" in body["error"]


def test_panel_refuses_to_save_an_unresolvable_study(imaging_on: None, make_staff: Any) -> None:
    me = make_staff()
    with patch.object(lookups.science_http, "get_json", side_effect=science([OTHER])):
        status, body = reply(make_api(me, body=imaging_body()).create_favorite())
    assert status == 400
    assert "doesn't find XR chest 2 views first" in body["error"]
    assert not Favorite.objects.exists()


def test_admin_create_and_personal_update_refuse_an_unresolvable_study(imaging_on: None, make_staff: Any) -> None:
    me = make_staff()
    FavoritesAdmin.objects.create(staff_id=me.dbid)
    mine = favorite(me, kind="imaging", details=imaging_details())
    with patch.object(lookups.science_http, "get_json", side_effect=science([OTHER])):
        status, _ = reply(make_api(me, body=imaging_body()).admin_create())
        assert status == 400
        status, _ = reply(make_api(me, path={"favorite_id": str(mine.dbid)}, body=imaging_body(name="Renamed")).update_favorite())
        assert status == 400
    assert list(Favorite.objects.values_list("name", flat=True)) == ["Fav"]


def test_adding_nothing_is_refused(make_staff: Any, make_note: Any) -> None:
    status, body, _r = add(make_staff(), make_note(), [])
    assert (status, body["error"]) == (400, "Select favorites to add.")


def test_admin_update_refuses_an_unresolvable_study(make_staff: Any) -> None:
    admin = make_staff()
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    fav = favorite(admin, kind="imaging", shared=True, details=imaging_details())
    with patch.object(lookups.science_http, "get_json", side_effect=science([])):
        status, _ = reply(make_api(admin, path={"favorite_id": str(fav.dbid)}, body=imaging_body(name="Renamed")).admin_update())
    assert status == 400
    fav.refresh_from_db()
    assert fav.name == "Fav"


# ---------- the order type setting ----------

def test_imaging_starts_off_and_is_refused_until_turned_on(chest_first: Any, make_staff: Any, make_note: Any) -> None:
    admin = make_staff()
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    old = favorite(admin, kind="imaging", details=imaging_details())
    note = make_note()

    status, body = reply(make_api(admin, body=imaging_body()).create_favorite())
    assert (status, body["error"]) == (400, "Your practice doesn't use this order type.")
    _s, data = reply(make_api(admin, query={"note_id": str(note.id)}).panel_data())
    assert "imaging" not in data["kinds"]
    assert all(f["kind"] != "imaging" for f in data["favorites"])
    status, _b, results = add(admin, note, [old.dbid])
    assert status == 404
    assert effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND") == []

    status, body = reply(make_api(admin, body={"imaging_enabled": True}).admin_settings())
    assert (status, body["title"]) == (200, "Prescription, Lab, and Imaging Order Favorites")
    assert body["settings"]["imaging_enabled"] is True
    status, _ = reply(make_api(admin, body=imaging_body()).create_favorite())
    assert status == 201


def test_imaging_alone_can_stay_on_but_not_none(make_staff: Any) -> None:
    admin = make_staff()
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    status, body = reply(make_api(admin, body={"rx_enabled": False, "lab_enabled": False, "imaging_enabled": True}).admin_settings())
    assert (status, body["title"]) == (200, "Imaging Order Favorites")
    status, body = reply(make_api(admin, body={"imaging_enabled": False}).admin_settings())
    assert (status, body["error"]) == (400, "At least one of prescriptions, labs, or imaging must stay on.")


@pytest.mark.parametrize(
    ("kinds", "title"),
    [
        (["rx"], "Prescription Favorites"),
        (["lab"], "Lab Order Favorites"),
        (["rx", "lab"], "Prescription and Lab Order Favorites"),
        (["lab", "imaging"], "Lab and Imaging Order Favorites"),
        (["rx", "lab", "imaging"], "Prescription, Lab, and Imaging Order Favorites"),
    ],
)
def test_title_names_the_order_types(kinds: list[str], title: str) -> None:
    assert _title(kinds) == title


# ---------- adding to a note ----------

def test_imaging_order_carries_every_saved_field(imaging_on: None, chest_first: Any, make_staff: Any, make_note: Any) -> None:
    saved = make_staff(first="Saved", npi=NPI)
    me = make_staff(first="Adder")
    details = imaging_details(
        diagnoses=[{"code": "R059", "text": "Cough"}],
        priority="Urgent",
        additional_details="Rule out pneumonia",
        comment="Call with results",
        ordering_provider_id=str(saved.id),
        imaging_center=CENTER,
    )
    fav = favorite(me, kind="imaging", details=details)
    note = make_note()
    status, body, results = add(me, note, [fav.dbid])
    assert status == 200
    [order] = effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND")
    assert order["note_uuid"] == str(note.id)
    assert order["image_code"] == "71046"
    assert order["diagnosis_codes"] == ["R059"]
    assert order["priority"] == "Urgent"
    assert order["additional_details"] == "Rule out pneumonia"
    assert order["comment"] == "Call with results"
    assert order["ordering_provider_key"] == str(saved.id)
    assert order["service_provider"]["practice_name"] == "Main Imaging"
    assert order["service_provider"]["business_fax"] == "5550001111"
    assert [a["id"] for a in body["added"]] == [fav.dbid]


def test_imaging_order_leaves_blank_fields_out_and_names_the_note_provider(imaging_on: None, chest_first: Any, make_staff: Any, make_note: Any) -> None:
    provider = make_staff(first="Note", npi=NPI)
    me = make_staff()
    _s, _b, results = add(me, make_note(provider=provider), [favorite(me, kind="imaging", details=imaging_details()).dbid])
    [order] = effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND")
    assert order["ordering_provider_key"] == str(provider.id)
    for field in ("priority", "additional_details", "comment", "service_provider"):
        assert order.get(field) is None


@pytest.mark.parametrize(
    ("side", "reason"),
    [
        (science([OTHER, CHEST]), "image"),
        (science([]), "image"),
        (RequestException("down"), "image_check"),
        (science([CHEST], status=503), "image_check"),
    ],
)
def test_imaging_favorite_canvas_cant_resolve_is_skipped_whole(imaging_on: None, side: Any, reason: str, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    img = favorite(me, kind="imaging", name="Chest x-ray", details=imaging_details())
    rx = favorite(me, name="Amox")
    with patch.object(lookups.science_http, "get_json", side_effect=side):
        status, body, results = add(me, make_note(), [img.dbid, rx.dbid])
    assert status == 200
    assert effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND") == []
    assert len(effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")) == 1
    assert body["skipped"] == [{"id": img.dbid, "name": "Chest x-ray", "kind": "imaging", "shared": False, "reason": reason, "image": "XR chest 2 views"}]


@pytest.mark.parametrize(
    ("side", "flagged"),
    [
        (science([OTHER, CHEST]), True),
        (science([]), True),
        (RequestException("down"), False),
        (science([CHEST], status=503), False),
    ],
)
def test_skipped_imaging_favorite_needs_fixing_only_when_the_search_moved(imaging_on: None, side: Any, flagged: bool, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    img = favorite(me, kind="imaging", details=imaging_details())
    with patch.object(lookups.science_http, "get_json", side_effect=side):
        add(me, make_note(), [img.dbid])
    img = Favorite.objects.get(dbid=img.dbid)
    assert bool(img.details.get("unresolved")) is flagged
    assert stale_map([img]) == ({img.dbid: ["71046"]} if flagged else {})


def test_needs_fixing_clears_when_a_later_add_finds_the_study(imaging_on: None, chest_first: Any, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    img = favorite(me, kind="imaging", details={**imaging_details(), "unresolved": True})
    _s, body, results = add(me, make_note(), [img.dbid])
    assert len(effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND")) == 1
    img = Favorite.objects.get(dbid=img.dbid)
    assert "unresolved" not in img.details
    assert stale_map([img]) == {}


def test_needs_fixing_keeps_an_edit_saved_while_the_search_answered(imaging_on: None, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    img = favorite(me, kind="imaging", name="Chest x-ray", details=imaging_details())

    answer = science([OTHER, CHEST])

    def edit_then_answer(path: str) -> Any:
        edited = Favorite.objects.get(dbid=img.dbid)
        edited.name = "Chest x-ray, renamed"
        edited.details = {**edited.details, "comment": "edited"}
        edited.save()
        return answer(path)

    with patch.object(lookups.science_http, "get_json", side_effect=edit_then_answer):
        add(me, make_note(), [img.dbid])
    stored = Favorite.objects.get(dbid=img.dbid)
    assert stored.name == "Chest x-ray, renamed"
    assert stored.details["comment"] == "edited"
    assert stored.details["unresolved"] is True


def test_resaving_an_imaging_favorite_drops_needs_fixing(imaging_on: None, chest_first: Any, make_staff: Any) -> None:
    me = make_staff()
    _k, _n, details = clean_favorite({"kind": "imaging", "name": "Chest", **imaging_details(), "unresolved": True}, owner=me.dbid)
    assert "unresolved" not in details


def test_imaging_favorite_without_a_code_is_skipped(imaging_on: None, chest_first: Any, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    fav = favorite(me, kind="imaging", details=imaging_details(image_code=""))
    _s, body, results = add(me, make_note(), [fav.dbid])
    assert effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND") == []
    assert body["skipped"][0]["reason"] == "image"


# ---------- order sets ----------

def test_order_set_holds_and_adds_imaging_favorites(imaging_on: None, chest_first: Any, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    img = favorite(me, kind="imaging", name="Chest x-ray", details=imaging_details())
    rx = favorite(me, name="Amox")
    _k, _n, details = clean_favorite({"kind": "set", "name": "Cough visit", "items": [img.dbid, rx.dbid]}, owner=me.dbid)
    bundle = Favorite.objects.create(kind="set", name="Cough visit", owner_id=me.dbid, details=details)
    _s, body, results = add(me, make_note(), [bundle.dbid])
    assert [a["name"] for a in body["added"]] == ["Chest x-ray", "Amox"]
    assert len(effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND")) == 1

    set_setting("imaging_enabled", False)
    _s, body, results = add(me, make_note(), [bundle.dbid])
    assert [a["name"] for a in body["added"]] == ["Amox"]
    assert effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND") == []


# ---------- import ----------

def test_import_imaging_rows(chest_first: Any) -> None:
    text = (
        "type,name,details\n"
        "imaging,Chest x-ray,71046|R05.9|stat|Rule out pneumonia|Call with results\n"
        "imaging,No code,\n"
        "imaging,Bad priority,71046||soon\n"
        "imaging,Wrong study,71045\n"
        "imaging,Bad indication,71046|cough\n"
    )
    with patch("order_favorites.services.importer.find_diagnosis", side_effect=lambda c: {"code": "R059", "text": "Cough"} if c == "R05.9" else None):
        rows = {r["row"]: r for r in check_csv(text)["rows"]}
    assert rows[2]["ok"] and rows[2]["summary"] == "XR chest 2 views · STAT · R05.9"
    saved = rows[2]["favorite"]["details"]
    assert (saved["image_code"], saved["priority"], saved["additional_details"], saved["imaging_center"]) == ("71046", "STAT", "Rule out pneumonia", None)
    assert rows[3]["reason"] == "The study code is missing."
    assert rows[4]["reason"] == "Priority must be Routine, Urgent, or STAT."
    assert "doesn't find 71045 first" in rows[5]["reason"]
    assert rows[6]["reason"] == "cough isn't an ICD-10 code."


def test_import_imaging_row_without_extras_summarizes_the_study(chest_first: Any) -> None:
    [row] = check_csv("type,name,details\nimaging,Chest x-ray,71046\n")["rows"]
    assert row["ok"] and row["summary"] == "XR chest 2 views"


# ---------- searches ----------

def test_imaging_search_keeps_one_row_per_study_and_needs_a_code_and_name(make_staff: Any) -> None:
    rows = [CHEST, dict(CHEST), {**CHEST, "code_system": "SNOMED"}, {"name": "", "code": "1", "code_system": "x"}, {"name": "No code", "code": "", "code_system": "x"}, "junk"]
    with patch.object(lookups.science_http, "get_json", side_effect=science(rows)):
        status, body = reply(make_api(make_staff(), query={"q": "chest"}).imaging())
    assert status == 200
    assert body["results"] == [CHEST, {**CHEST, "code_system": "SNOMED"}]


def test_imaging_search_stops_at_the_result_limit() -> None:
    rows = [{"name": f"Study {i}", "code": str(i), "code_system": "CPT"} for i in range(30)]
    with patch.object(lookups.science_http, "get_json", side_effect=science(rows)):
        assert len(lookups.search_imaging("study")) == lookups.MAX_RESULTS


def test_imaging_center_search_returns_order_fields(make_staff: Any) -> None:
    contacts = [
        {"id": 9, "firstName": None, "lastName": "Lee", "practiceName": "Main Imaging", "specialty": "Radiology", "businessFax": "5550001111", "businessPhone": None, "businessAddress": "1 Main St", "notes": None},
        {"id": 10, "firstName": "", "lastName": "", "practiceName": ""},
    ]
    fake = science(centers=contacts)
    with patch.object(lookups.science_http, "get_json", side_effect=fake):
        status, body = reply(make_api(make_staff(), query={"q": "main"}).imaging_centers())
    assert status == 200
    assert body["results"] == [{**CENTER, "last_name": "Lee"}]
    assert fake.paths == ["/contacts/?search=main&job_title__icontains=radiology"]


def test_imaging_center_search_stops_at_the_result_limit() -> None:
    contacts = [{"practiceName": f"Center {i}"} for i in range(30)]
    with patch.object(lookups.science_http, "get_json", side_effect=science(centers=contacts)):
        assert len(lookups.search_imaging_centers("center")) == lookups.MAX_RESULTS


@pytest.mark.parametrize("route", ["imaging", "imaging_centers"])
def test_imaging_searches_answer_503_when_science_is_down_and_need_two_letters(route: str, make_staff: Any) -> None:
    me = make_staff()
    for side in (RequestException("down"), science(status=500)):
        with patch.object(lookups.science_http, "get_json", side_effect=side):
            status, _ = reply(getattr(make_api(me, query={"q": "chest"}), route)())
        assert status == 503
    _s, body = reply(getattr(make_api(me, query={"q": "c"}), route)())
    assert body == {"results": []}


def test_check_image_refuses_a_science_answer_without_results() -> None:
    with patch.object(lookups.science_http, "get_json", return_value=SimpleNamespace(status_code=200, json=lambda: None)), pytest.raises(lookups.LookupFailed):
        lookups.check_image("71046")
    assert lookups.check_image("  ") is None


def test_check_image_treats_a_non_json_science_answer_as_down() -> None:
    def not_json() -> None:
        raise ValueError("Expecting value")

    with patch.object(lookups.science_http, "get_json", return_value=SimpleNamespace(status_code=502, json=not_json)), pytest.raises(lookups.LookupFailed):
        lookups.check_image("71046")


def test_imaging_center_with_only_a_last_name_saves(chest_first: Any) -> None:
    center = {**CENTER, "practice_name": "", "last_name": "Rivera"}
    _k, _n, details = clean_favorite(imaging_body(imaging_center=center))
    assert details["imaging_center"]["last_name"] == "Rivera"
    assert details["imaging_center"]["practice_name"] == ""


@pytest.mark.parametrize("body", [{"kind": "set", "name": "S", "items": 7}, {"kind": "lab", "name": "L", "lab_partner_id": "x", "tests": "CBC"}])
def test_non_list_items_and_tests_are_refused_not_crashed(body: dict[str, Any]) -> None:
    with pytest.raises(Invalid):
        clean_favorite(body, owner=1)


def test_adding_favorites_with_the_same_study_searches_science_once(imaging_on: None, chest_first: Any, make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    ids = [favorite(me, kind="imaging", name=f"Chest {n}", details=imaging_details()).dbid for n in range(3)]
    _s, body, results = add(me, make_note(), ids)
    assert len(body["added"]) == 3
    assert len(effects_of(results, "ORIGINATE_IMAGING_ORDER_COMMAND")) == 3
    assert len(chest_first.paths) == 1


def test_import_searches_science_once_per_study(chest_first: Any) -> None:
    text = "type,name,details\n" + "".join(f"imaging,Chest {n},71046\n" for n in range(5))
    rows = check_csv(text)["rows"]
    assert all(r["ok"] for r in rows)
    assert len(chest_first.paths) == 1


def test_after_science_fails_once_the_rest_of_the_request_does_not_wait_on_it() -> None:
    calls: list[str] = []

    def down(path: str) -> Any:
        calls.append(path)
        raise RequestException("timeout")

    cache: dict[tuple[str, str], Any] = {}
    with patch.object(lookups.science_http, "get_json", side_effect=down):
        for code in ("71046", "70450", "71046"):
            with pytest.raises(lookups.LookupFailed):
                lookups.check_image(code, "CPT", cache)
    assert len(calls) == 1


def test_image_code_matches_science_ignoring_case_and_keeps_science_code() -> None:
    study = {"name": "US breast bilateral", "code_system": "CPT", "code": "76641-RT"}
    with patch.object(lookups.science_http, "get_json", side_effect=science([study])):
        assert lookups.check_image(" 76641-rt ") == study


@pytest.mark.parametrize("answer", [SimpleNamespace(status_code=500, json=lambda: {"detail": "error"}), SimpleNamespace(status_code=200, json=lambda: ["not", "an", "object"])])
def test_diagnosis_search_error_is_an_outage_not_no_matches(answer: Any) -> None:
    with patch.object(lookups.science_http, "get_json", return_value=answer), pytest.raises(lookups.LookupFailed):
        lookups.search_diagnoses("cough")


def test_import_reports_a_diagnosis_outage_instead_of_a_bad_code() -> None:
    studies = science([CHEST])

    def condition_search_down(path: str) -> Any:
        if path.startswith("/search/condition/"):
            return SimpleNamespace(status_code=502, json=dict)
        return studies(path)

    with patch.object(lookups.science_http, "get_json", side_effect=condition_search_down):
        [row] = check_csv("type,name,details\nimaging,Chest,71046|R05.9\n")["rows"]
    assert not row["ok"]
    assert "didn't answer" in row["reason"]
