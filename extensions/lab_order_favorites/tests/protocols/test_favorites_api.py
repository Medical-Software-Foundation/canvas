"""Tests for the favorites SimpleAPI routes."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from lab_order_favorites.protocols import favorites_api
from lab_order_favorites.protocols.favorites_api import (
    CreateChartReviewAPI,
    CSVImportAPI,
    CSVTemplateAPI,
    FavoritesAPI,
    InsertFavoriteAPI,
    OpenNotesAPI,
    PartnersAPI,
    PartnerTestsAPI,
    ProvidersAPI,
)
from lab_order_favorites.services import FavoritesService

TESTS = [{"order_code": "001", "order_name": "Glucose", "cpt_code": "82947"}]


def _route(cls, request, secrets=None):
    """Build a route handler with a fake request (event is unused by the routes)."""
    handler = cls(MagicMock())
    handler.request = request
    handler.secrets = secrets or {}
    return handler


def _body(response) -> dict[str, Any]:
    import json

    return json.loads(response.content.decode())


class FakeNote:
    def __init__(self, note_id: str, title: str = "Office Visit") -> None:
        self.id = note_id
        self.title = title
        self.modified = None
        self.note_type_version = None


# --- FavoritesAPI ---

def test_get_favorites_requires_staff(make_request):
    handler = _route(FavoritesAPI, make_request(staff_id=""))
    [resp] = handler.get()
    assert resp.status_code == 400


def test_get_favorites_lists_with_search(make_request, make_staff):
    staff = make_staff()
    FavoritesService().create_favorite(
        {"name": "Glucose", "lab_partner_id": "p1", "lab_partner_name": "LabCorp", "tests": TESTS},
        str(staff.id),
    )
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), query={"filter": "all", "search": "glucose"}))
    [resp] = handler.get()
    data = _body(resp)
    assert data["success"] is True
    assert data["count"] == 1


def test_post_create_success(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    body = {
        "name": "Glucose",
        "lab_partner_id": str(partner.id),
        "lab_partner_name": partner.name,
        "tests": [{"order_code": "001", "order_name": "Glucose", "cpt_code": ""}],
    }
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    data = _body(resp)
    assert data["success"] is True
    assert data["favorite"]["name"] == "Glucose"


def test_post_create_blocks_stale_codes(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    body = {
        "name": "Bad",
        "lab_partner_id": str(partner.id),
        "tests": [{"order_code": "999", "order_name": "Gone", "cpt_code": ""}],
    }
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    data = _body(resp)
    assert resp.status_code == 400
    assert data["stale_codes"] == ["999"]


def test_post_missing_partner_id_rejected(make_request, make_staff):
    staff = make_staff()
    body = {"name": "X", "tests": TESTS}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 400
    assert "lab_partner_id" in _body(resp)["error"]


def test_post_missing_tests_rejected(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    body = {"name": "X", "lab_partner_id": str(partner.id), "tests": []}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 400
    assert "order code" in _body(resp)["error"]


def test_post_unknown_partner_rejected(make_request, make_staff):
    staff = make_staff()
    body = {"name": "X", "lab_partner_id": "ghost", "tests": TESTS}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 400
    assert _body(resp)["error"] == "Lab partner not found"


def test_post_inactive_partner_rejected(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(name="Dormant", active=False, tests=[("001", "Glucose")])
    body = {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 400
    assert "not active" in _body(resp)["error"]


def test_post_requires_staff(make_request):
    handler = _route(FavoritesAPI, make_request(staff_id="", body={}))
    [resp] = handler.post()
    assert resp.status_code == 400


def test_post_invalid_json(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(side_effect=ValueError("bad"))
    request.body = b"not json"
    handler = _route(FavoritesAPI, request)
    [resp] = handler.post()
    assert resp.status_code == 400


def test_put_not_owner_forbidden(make_request, make_staff, make_partner):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(other.id)
    )
    handler = _route(FavoritesAPI, make_request(staff_id=str(me.id), body={"id": created["id"], "name": "Y"}))
    [resp] = handler.put()
    assert resp.status_code == 403


def test_put_updates_and_revalidates(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(staff.id)
    )
    new_tests = [{"order_code": "002", "order_name": "Lipid", "cpt_code": ""}]
    handler = _route(
        FavoritesAPI,
        make_request(staff_id=str(staff.id), body={"id": created["id"], "tests": new_tests, "lab_partner_id": str(partner.id)}),
    )
    [resp] = handler.put()
    data = _body(resp)
    assert data["success"] is True
    assert data["favorite"]["tests"][0]["order_code"] == "002"


def test_put_missing_id(make_request, make_staff):
    staff = make_staff()
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body={}))
    [resp] = handler.put()
    assert resp.status_code == 400


def test_put_not_found(make_request, make_staff):
    staff = make_staff()
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body={"id": "labfav_missing", "name": "Y"}))
    [resp] = handler.put()
    assert resp.status_code == 404


def test_delete_success_and_authz(make_request, make_staff, make_partner):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(me.id)
    )
    # Not owner.
    h1 = _route(FavoritesAPI, make_request(staff_id=str(other.id), query={"id": created["id"]}))
    [resp1] = h1.delete()
    assert resp1.status_code == 403
    # Owner.
    h2 = _route(FavoritesAPI, make_request(staff_id=str(me.id), query={"id": created["id"]}))
    [resp2] = h2.delete()
    assert _body(resp2)["success"] is True


def test_allowlisted_editor_can_edit_shared(make_request, make_staff, make_partner):
    author = make_staff(first_name="Author")
    editor = make_staff(first_name="Editor")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": True}, str(author.id)
    )
    secrets = {"SHARED_FAVORITE_EDITORS": f"someone-else, {editor.id}"}
    handler = _route(
        FavoritesAPI,
        make_request(staff_id=str(editor.id), body={"id": created["id"], "name": "Edited"}),
        secrets=secrets,
    )
    [resp] = handler.put()
    assert _body(resp)["success"] is True
    assert _body(resp)["favorite"]["name"] == "Edited"


def test_allowlisted_editor_can_delete_shared(make_request, make_staff, make_partner):
    author = make_staff(first_name="Author")
    editor = make_staff(first_name="Editor")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": True}, str(author.id)
    )
    handler = _route(
        FavoritesAPI,
        make_request(staff_id=str(editor.id), query={"id": created["id"]}),
        secrets={"SHARED_FAVORITE_EDITORS": str(editor.id)},
    )
    [resp] = handler.delete()
    assert _body(resp)["success"] is True


def test_allowlisted_editor_cannot_edit_personal(make_request, make_staff, make_partner):
    author = make_staff(first_name="Author")
    editor = make_staff(first_name="Editor")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": False}, str(author.id)
    )
    handler = _route(
        FavoritesAPI,
        make_request(staff_id=str(editor.id), body={"id": created["id"], "name": "Nope"}),
        secrets={"SHARED_FAVORITE_EDITORS": str(editor.id)},
    )
    [resp] = handler.put()
    assert resp.status_code == 403


def test_root_can_edit_any_favorite(make_request, make_staff, make_partner):
    author = make_staff(first_name="Author")
    partner = make_partner(tests=[("001", "Glucose")])
    # A personal favorite root does not own and is not in any allowlist.
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": False}, str(author.id)
    )
    handler = _route(
        FavoritesAPI,
        make_request(staff_id="root", body={"id": created["id"], "name": "Edited by root"}),
    )
    [resp] = handler.put()
    assert _body(resp)["success"] is True
    assert _body(resp)["favorite"]["name"] == "Edited by root"


def test_root_can_delete_any_favorite(make_request, make_staff, make_partner):
    author = make_staff(first_name="Author")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": False}, str(author.id)
    )
    handler = _route(FavoritesAPI, make_request(staff_id="root", query={"id": created["id"]}))
    [resp] = handler.delete()
    assert _body(resp)["success"] is True


def test_delete_missing_id(make_request, make_staff):
    staff = make_staff()
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), query={}))
    [resp] = handler.delete()
    assert resp.status_code == 400


def test_delete_not_found(make_request, make_staff):
    staff = make_staff()
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), query={"id": "labfav_missing"}))
    [resp] = handler.delete()
    assert resp.status_code == 404


# --- PartnersAPI / PartnerTestsAPI ---

def test_partners_list(make_request, make_partner):
    make_partner(name="Quest", active=True)
    make_partner(name="Dead", active=False)
    handler = _route(PartnersAPI, make_request())
    [resp] = handler.get()
    data = _body(resp)
    assert [p["name"] for p in data["partners"]] == ["Quest"]


def test_partner_tests_requires_partner_id(make_request):
    handler = _route(PartnerTestsAPI, make_request(query={}))
    [resp] = handler.get()
    assert resp.status_code == 400


def test_partner_tests_list(make_request, make_partner):
    partner = make_partner(tests=[("001", "Glucose")])
    handler = _route(PartnerTestsAPI, make_request(query={"partner_id": str(partner.id)}))
    [resp] = handler.get()
    data = _body(resp)
    assert data["tests"][0]["order_code"] == "001"


# --- CSVTemplateAPI ---

def test_config_page_served(make_request):
    from lab_order_favorites.protocols.favorites_api import ConfigPageAPI

    handler = _route(ConfigPageAPI, make_request())
    with patch.object(favorites_api, "render_to_string", return_value="<html>config</html>") as render:
        [resp] = handler.get()
    assert resp.status_code == 200
    assert b"config" in resp.content
    template, context = render.call_args[0]
    assert template == "templates/config.html"
    assert context["api_base"] == "/plugin-io/api/lab_order_favorites"


def test_csv_template_download(make_request):
    handler = _route(CSVTemplateAPI, make_request())
    [resp] = handler.get()
    assert resp.status_code == 200
    assert "text/csv" in (resp.headers.get("Content-Type", ""))
    assert b"lab_partner" in resp.content


# --- CSVImportAPI ---

def test_csv_import_preview_and_commit(make_request, make_staff, make_partner):
    staff = make_staff()
    make_partner(name="LabCorp", tests=[("001", "Glucose"), ("002", "Lipid")])
    csv = (
        "name,lab_partner,test_order_codes,tags\n"
        "Panel,LabCorp,001;002,wellness\n"
        "Bad,LabCorp,999,\n"
        "NoPartner,Ghost,001,\n"
    )
    # Preview.
    h1 = _route(CSVImportAPI, make_request(staff_id=str(staff.id), body={"csv": csv, "commit": False}))
    [resp1] = h1.post()
    data1 = _body(resp1)
    assert data1["ready_count"] == 1
    assert data1["error_count"] == 2  # stale code row + unknown partner row

    # Commit.
    h2 = _route(CSVImportAPI, make_request(staff_id=str(staff.id), body={"csv": csv, "commit": True}))
    [resp2] = h2.post()
    data2 = _body(resp2)
    assert data2["created"] == 1


def test_csv_import_requires_content(make_request, make_staff):
    staff = make_staff()
    handler = _route(CSVImportAPI, make_request(staff_id=str(staff.id), body={"csv": "   "}))
    [resp] = handler.post()
    assert resp.status_code == 400


def test_csv_import_requires_staff(make_request):
    handler = _route(CSVImportAPI, make_request(staff_id="", body={"csv": "x"}))
    [resp] = handler.post()
    assert resp.status_code == 400


# --- OpenNotesAPI ---

def test_open_notes_requires_patient(make_request):
    handler = _route(OpenNotesAPI, make_request(query={}))
    [resp] = handler.get()
    assert resp.status_code == 400


def test_open_notes_lists(make_request):
    handler = _route(OpenNotesAPI, make_request(query={"patient_id": "pat-1"}))
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]):
        [resp] = handler.get()
    data = _body(resp)
    assert data["notes"][0]["id"] == "note-1"
    assert data["notes"][0]["title"] == "Office Visit"


# --- InsertFavoriteAPI ---

def _make_favorite(staff, partner, codes):
    tests = [{"order_code": c, "order_name": c, "cpt_code": ""} for c in codes]
    return FavoritesService().create_favorite(
        {
            "name": "Panel",
            "lab_partner_id": str(partner.id),
            "lab_partner_name": partner.name,
            "tests": tests,
            "diagnosis_codes": ["Z00.00"],
            "fasting_required": True,
            "comment": "fast",
        },
        str(staff.id),
    )


def test_insert_single_builds_staged_lab_order(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid")])
    fav = _make_favorite(staff, partner, ["001", "002"])
    body = {"favorite_id": fav["id"], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))

    fake_cmd = MagicMock()
    fake_cmd.originate.return_value = "ORDER_EFFECT"
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        result = handler.post()

    data = _body(result[0])
    assert data["success"] is True
    assert len(data["inserted"]) == 1
    assert data["skipped"] == []
    assert result[1] == "ORDER_EFFECT"
    _, kwargs = cmd_cls.call_args
    assert kwargs["note_uuid"] == "note-1"
    assert kwargs["lab_partner"] == str(partner.id)
    assert kwargs["tests_order_codes"] == ["001", "002"]
    assert kwargs["ordering_provider_key"] == str(staff.id)
    assert kwargs["diagnosis_codes"] == ["Z00.00"]
    assert kwargs["fasting_required"] is True
    assert kwargs["comment"] == "fast"


def test_insert_multiple_favorites(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid")])
    fav1 = _make_favorite(staff, partner, ["001"])
    fav2 = _make_favorite(staff, partner, ["002"])
    body = {"favorite_ids": [fav1["id"], fav2["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))

    fake_cmd = MagicMock()
    fake_cmd.originate.return_value = "EFFECT"
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        result = handler.post()

    data = _body(result[0])
    assert len(data["inserted"]) == 2
    assert data["skipped"] == []
    assert result[1:] == ["EFFECT", "EFFECT"]  # one effect per favorite
    assert cmd_cls.call_count == 2


def test_insert_mixed_valid_and_stale(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    good = _make_favorite(staff, partner, ["001"])
    bad = FavoritesService().create_favorite(
        {"name": "Bad", "lab_partner_id": str(partner.id), "tests": [{"order_code": "999", "order_name": "Gone", "cpt_code": ""}]},
        str(staff.id),
    )
    body = {"favorite_ids": [good["id"], bad["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))

    fake_cmd = MagicMock()
    fake_cmd.originate.return_value = "EFFECT"
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        result = handler.post()

    data = _body(result[0])
    assert [i["favorite_id"] for i in data["inserted"]] == [good["id"]]
    assert len(data["skipped"]) == 1
    skip = data["skipped"][0]
    assert skip["favorite_id"] == bad["id"]
    assert skip["reason"] == "stale_codes"
    assert skip["stale_codes"] == ["999"]
    assert skip["can_edit"] is True  # author can fix
    assert cmd_cls.call_count == 1  # only the good one staged


def test_insert_skip_stale_non_owner_cannot_edit(make_request, make_staff, make_partner):
    owner = make_staff(first_name="Owner", last_name="Doc")
    other = make_staff(first_name="Other", last_name="User")
    partner = make_partner(tests=[("001", "Glucose")])
    fav = _make_favorite(owner, partner, ["001"])  # shared by default
    partner.available_tests.all().delete()
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(other.id), body=body))
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand") as cmd_cls:
        result = handler.post()
    skip = _body(result[0])["skipped"][0]
    assert skip["reason"] == "stale_codes"
    assert skip["can_edit"] is False
    assert skip["owner_name"] == "Owner Doc"
    assert not cmd_cls.called


def test_insert_skip_inactive_partner(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    fav = _make_favorite(staff, partner, ["001"])
    partner.active = False
    partner.save()
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand") as cmd_cls:
        result = handler.post()
    assert _body(result[0])["skipped"][0]["reason"] == "partner_inactive"
    assert not cmd_cls.called


def test_insert_skip_partner_missing(make_request, make_staff):
    staff = make_staff()
    fav = FavoritesService().create_favorite(
        {"name": "Orphan", "lab_partner_id": "ghost", "tests": TESTS}, str(staff.id)
    )
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand") as cmd_cls:
        result = handler.post()
    assert _body(result[0])["skipped"][0]["reason"] == "partner_missing"
    assert not cmd_cls.called


def test_insert_skips_code_from_another_lab(make_request, make_staff, make_partner):
    staff = make_staff()
    lab_a = make_partner(name="Lab A", tests=[("AAA", "Test A")])
    make_partner(name="Lab B", tests=[("BBB", "Test B")])
    # Favorite bound to Lab A but storing Lab B's code (which exists, but not for Lab A).
    fav = FavoritesService().create_favorite(
        {"name": "Cross", "lab_partner_id": str(lab_a.id), "tests": [{"order_code": "BBB", "order_name": "Test B", "cpt_code": ""}]},
        str(staff.id),
    )
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand") as cmd_cls:
        result = handler.post()
    skip = _body(result[0])["skipped"][0]
    assert skip["reason"] == "stale_codes"
    assert skip["stale_codes"] == ["BBB"]
    assert not cmd_cls.called


def test_insert_skip_unknown_favorite(make_request, make_staff):
    staff = make_staff()
    body = {"favorite_ids": ["labfav_missing"], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]):
        result = handler.post()
    data = _body(result[0])
    assert data["skipped"][0]["reason"] == "not_found"
    assert data["inserted"] == []


def test_insert_rejects_note_not_open(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    fav = _make_favorite(staff, partner, ["001"])
    body = {"favorite_id": fav["id"], "patient_id": "pat-1", "note_uuid": "other-note"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))

    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]):
        [resp] = handler.post()

    assert resp.status_code == 400


def test_insert_requires_fields(make_request, make_staff):
    staff = make_staff()
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body={"favorite_id": "x"}))
    [resp] = handler.post()
    assert resp.status_code == 400


def test_insert_requires_staff(make_request):
    handler = _route(InsertFavoriteAPI, make_request(staff_id="", body={}))
    [resp] = handler.post()
    assert resp.status_code == 400


# --- ordering provider on the favorite ---

def test_providers_list(make_request, make_staff):
    make_staff(first_name="Real", last_name="Doc", npi_number="1234567890")
    make_staff(first_name="No", last_name="Npi", npi_number="")
    handler = _route(ProvidersAPI, make_request(query={"search": ""}))
    [resp] = handler.get()
    assert [p["name"] for p in _body(resp)["providers"]] == ["Real Doc"]


def test_create_with_valid_provider(make_request, make_staff, make_partner):
    staff = make_staff()
    provider = make_staff(first_name="Order", last_name="Doc", npi_number="1234567890")
    partner = make_partner(tests=[("001", "Glucose")])
    body = {"name": "Panel", "lab_partner_id": str(partner.id), "tests": TESTS, "ordering_provider_key": str(provider.id)}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    data = _body(resp)
    assert data["favorite"]["ordering_provider_key"] == str(provider.id)
    assert data["favorite"]["ordering_provider_name"] == "Order Doc"


def test_create_with_invalid_provider_rejected(make_request, make_staff, make_partner):
    staff = make_staff()
    bad = make_staff(first_name="No", last_name="Npi", npi_number="")
    partner = make_partner(tests=[("001", "Glucose")])
    body = {"name": "Panel", "lab_partner_id": str(partner.id), "tests": TESTS, "ordering_provider_key": str(bad.id)}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 400
    assert "valid NPI" in _body(resp)["error"]


def test_put_clear_provider(make_request, make_staff, make_partner):
    staff = make_staff()
    provider = make_staff(first_name="Order", last_name="Doc", npi_number="1234567890")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS, "ordering_provider_key": str(provider.id), "ordering_provider_name": "Order Doc"},
        str(staff.id),
    )
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body={"id": created["id"], "ordering_provider_key": ""}))
    [resp] = handler.put()
    assert _body(resp)["favorite"]["ordering_provider_key"] == ""
    assert _body(resp)["favorite"]["ordering_provider_name"] == ""


def test_put_invalid_provider_rejected(make_request, make_staff, make_partner):
    staff = make_staff()
    bad = make_staff(first_name="No", last_name="Npi", npi_number="")
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(staff.id)
    )
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body={"id": created["id"], "ordering_provider_key": str(bad.id)}))
    [resp] = handler.put()
    assert resp.status_code == 400


def test_insert_uses_favorite_provider(make_request, make_staff, make_partner):
    staff = make_staff()
    provider = make_staff(first_name="Order", last_name="Doc", npi_number="1234567890")
    partner = make_partner(tests=[("001", "Glucose")])
    fav = FavoritesService().create_favorite(
        {"name": "Panel", "lab_partner_id": str(partner.id), "tests": [{"order_code": "001", "order_name": "Glucose", "cpt_code": ""}], "ordering_provider_key": str(provider.id), "ordering_provider_name": "Order Doc"},
        str(staff.id),
    )
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    fake_cmd = MagicMock(); fake_cmd.originate.return_value = "E"
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        handler.post()
    assert cmd_cls.call_args.kwargs["ordering_provider_key"] == str(provider.id)


def test_insert_falls_back_to_staff_without_favorite_provider(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    fav = _make_favorite(staff, partner, ["001"])  # no provider set
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    fake_cmd = MagicMock(); fake_cmd.originate.return_value = "E"
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        handler.post()
    assert cmd_cls.call_args.kwargs["ordering_provider_key"] == str(staff.id)


def test_json_body_empty_returns_400(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(side_effect=ValueError("no json"))
    request.body = b""
    handler = _route(FavoritesAPI, request)
    [resp] = handler.post()
    assert resp.status_code == 400


def test_json_body_non_object_returns_400(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(return_value=["not", "a", "dict"])
    handler = _route(FavoritesAPI, request)
    [resp] = handler.post()
    assert resp.status_code == 400


def test_insert_drops_invalid_favorite_provider(make_request, make_staff, make_partner):
    staff = make_staff()
    provider = make_staff(first_name="Order", last_name="Doc", npi_number="1234567890")
    partner = make_partner(tests=[("001", "Glucose")])
    fav = FavoritesService().create_favorite(
        {"name": "P", "lab_partner_id": str(partner.id), "tests": [{"order_code": "001", "order_name": "Glucose", "cpt_code": ""}], "ordering_provider_key": str(provider.id)},
        str(staff.id),
    )
    # The saved provider loses its NPI after the favorite was created.
    provider.npi_number = ""
    provider.save()
    body = {"favorite_ids": [fav["id"]], "patient_id": "pat-1", "note_uuid": "note-1"}
    handler = _route(InsertFavoriteAPI, make_request(staff_id=str(staff.id), body=body))
    fake_cmd = MagicMock(); fake_cmd.originate.return_value = "E"
    with patch.object(favorites_api, "_open_notes_for_patient", return_value=[FakeNote("note-1")]), \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        handler.post()
    # No longer a valid provider -> falls back to the inserting staff member.
    assert cmd_cls.call_args.kwargs["ordering_provider_key"] == str(staff.id)


def test_list_annotates_can_edit(make_request, make_staff, make_partner):
    me = make_staff(first_name="Me")
    other = make_staff(first_name="Other")
    partner = make_partner(tests=[("001", "Glucose")])
    FavoritesService().create_favorite({"name": "Mine", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": True}, str(me.id))
    FavoritesService().create_favorite({"name": "Theirs", "lab_partner_id": str(partner.id), "tests": TESTS, "is_shared": True}, str(other.id))

    # No allowlist: I can edit my own shared favorite, not someone else's.
    handler = _route(FavoritesAPI, make_request(staff_id=str(me.id), query={"filter": "all"}))
    [resp] = handler.get()
    favs = {f["name"]: f for f in _body(resp)["favorites"]}
    assert favs["Mine"]["can_edit"] is True
    assert favs["Theirs"]["can_edit"] is False

    # Allowlisted: I can edit any shared favorite.
    handler2 = _route(FavoritesAPI, make_request(staff_id=str(me.id), query={"filter": "all"}), secrets={"SHARED_FAVORITE_EDITORS": str(me.id)})
    [resp2] = handler2.get()
    favs2 = {f["name"]: f for f in _body(resp2)["favorites"]}
    assert favs2["Theirs"]["can_edit"] is True


def test_requested_favorite_ids_dedupes_and_drops_blanks():
    assert favorites_api._requested_favorite_ids({"favorite_ids": ["a", "a", " ", "b"]}) == ["a", "b"]
    assert favorites_api._requested_favorite_ids({"favorite_id": "x"}) == ["x"]
    assert favorites_api._requested_favorite_ids({}) == []


def test_insert_invalid_json(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(side_effect=ValueError("bad"))
    request.body = b"x"
    handler = _route(InsertFavoriteAPI, request)
    [resp] = handler.post()
    assert resp.status_code == 400


# --- _json_body fallback paths ---

def test_json_body_falls_back_to_bytes(make_request):
    request = make_request()
    request.json = MagicMock(side_effect=ValueError("no json()"))
    request.body = b'{"a": 1}'
    handler = _route(FavoritesAPI, request)
    assert handler._json_body() == {"a": 1}


def test_json_body_falls_back_to_str(make_request):
    request = make_request()
    request.json = MagicMock(side_effect=ValueError("no json()"))
    request.body = '{"a": 2}'
    handler = _route(FavoritesAPI, request)
    assert handler._json_body() == {"a": 2}


# --- create/put/delete defensive paths ---

def test_post_create_value_error_returns_400(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    # Passes catalog validation but service rejects the empty name.
    body = {"name": "", "lab_partner_id": str(partner.id), "tests": TESTS}
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 400


def test_put_requires_staff(make_request):
    handler = _route(FavoritesAPI, make_request(staff_id="", body={"id": "x"}))
    [resp] = handler.put()
    assert resp.status_code == 400


def test_put_invalid_json(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(side_effect=ValueError("bad"))
    request.body = b"x"
    handler = _route(FavoritesAPI, request)
    [resp] = handler.put()
    assert resp.status_code == 400


def test_put_revalidation_blocks_stale(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(staff.id)
    )
    bad = [{"order_code": "999", "order_name": "Gone", "cpt_code": ""}]
    handler = _route(
        FavoritesAPI,
        make_request(staff_id=str(staff.id), body={"id": created["id"], "tests": bad}),
    )
    [resp] = handler.put()
    assert resp.status_code == 400
    assert _body(resp)["stale_codes"] == ["999"]


def test_put_value_error_returns_400(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(staff.id)
    )
    handler = _route(
        FavoritesAPI, make_request(staff_id=str(staff.id), body={"id": created["id"], "name": "  "})
    )
    [resp] = handler.put()
    assert resp.status_code == 400


def test_put_update_returns_none_is_500(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(staff.id)
    )
    handler = _route(
        FavoritesAPI, make_request(staff_id=str(staff.id), body={"id": created["id"], "name": "Y"})
    )
    with patch.object(FavoritesService, "update_favorite", return_value=None):
        [resp] = handler.put()
    assert resp.status_code == 500


def test_delete_requires_staff(make_request):
    handler = _route(FavoritesAPI, make_request(staff_id="", query={"id": "x"}))
    [resp] = handler.delete()
    assert resp.status_code == 400


def test_delete_returns_false_is_500(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose")])
    created = FavoritesService().create_favorite(
        {"name": "X", "lab_partner_id": str(partner.id), "tests": TESTS}, str(staff.id)
    )
    handler = _route(FavoritesAPI, make_request(staff_id=str(staff.id), query={"id": created["id"]}))
    with patch.object(FavoritesService, "delete_favorite", return_value=False):
        [resp] = handler.delete()
    assert resp.status_code == 500


def test_csv_import_invalid_json(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(side_effect=ValueError("bad"))
    request.body = b"x"
    handler = _route(CSVImportAPI, request)
    [resp] = handler.post()
    assert resp.status_code == 400


def test_csv_import_commit_create_failure_is_reported(make_request, make_staff, make_partner):
    staff = make_staff()
    make_partner(name="LabCorp", tests=[("001", "Glucose")])
    csv = "name,lab_partner,test_order_codes\nPanel,LabCorp,001\n"
    handler = _route(CSVImportAPI, make_request(staff_id=str(staff.id), body={"csv": csv, "commit": True}))
    with patch.object(FavoritesService, "create_favorite", side_effect=ValueError("boom")):
        [resp] = handler.post()
    data = _body(resp)
    assert data["created"] == 0
    assert data["error_count"] == 1


def test_open_notes_helper_unknown_patient_returns_empty():
    result = favorites_api._open_notes_for_patient("11111111-1111-1111-1111-111111111111")
    assert list(result) == []


def test_open_notes_helper_non_uuid_returns_empty():
    # A malformed patient_id must not 500 - it returns no open notes.
    assert list(favorites_api._open_notes_for_patient("not-a-uuid")) == []


def test_open_notes_helper_builds_filtered_queryset():
    patient = MagicMock()
    note_qs = MagicMock()
    note_qs.select_related.return_value.order_by.return_value = ["NOTE_QS"]
    with patch.object(favorites_api.Patient.objects, "get", return_value=patient), \
         patch.object(favorites_api.CurrentNoteStateEvent, "objects") as states, \
         patch.object(favorites_api.Note, "objects") as notes:
        states.filter.return_value.values_list.return_value = [1, 2]
        notes.filter.return_value = note_qs
        result = favorites_api._open_notes_for_patient("11111111-1111-1111-1111-111111111111")
    assert result == ["NOTE_QS"]
    assert notes.filter.call_args.kwargs["patient"] is patient
    # The open-note state filter is the safety gate (no staging into locked/signed notes).
    assert states.filter.call_args.kwargs["state__in"] == favorites_api.OPEN_NOTE_STATES
    # Only encounter and chart review notes are insert targets - messages/letters,
    # which never lock, are excluded by category.
    assert (
        notes.filter.call_args.kwargs["note_type_version__category__in"]
        == favorites_api.INSERT_TARGET_CATEGORIES
    )


# --- CreateChartReviewAPI ---

def test_create_review_requires_staff(make_request):
    handler = _route(CreateChartReviewAPI, make_request(staff_id="", body={}))
    [resp] = handler.post()
    assert resp.status_code == 400


def test_create_review_invalid_json(make_request, make_staff):
    staff = make_staff()
    request = make_request(staff_id=str(staff.id))
    request.json = MagicMock(side_effect=ValueError("bad"))
    request.body = b"x"
    handler = _route(CreateChartReviewAPI, request)
    [resp] = handler.post()
    assert resp.status_code == 400


def test_create_review_requires_fields(make_request, make_staff):
    staff = make_staff()
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body={"patient_id": ""}))
    [resp] = handler.post()
    assert resp.status_code == 400


def test_create_review_rejects_non_uuid_patient(make_request, make_staff):
    staff = make_staff()
    body = {"favorite_ids": ["x"], "patient_id": "not-a-uuid"}
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body=body))
    [resp] = handler.post()
    assert resp.status_code == 404


def test_create_review_patient_not_found(make_request, make_staff):
    staff = make_staff()
    pid = "11111111-1111-1111-1111-111111111111"
    body = {"favorite_ids": ["x"], "patient_id": pid}
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "Patient") as P:
        P.objects.filter.return_value.exists.return_value = False
        [resp] = handler.post()
    assert resp.status_code == 404


def test_create_review_no_chart_review_type_configured(make_request, make_staff):
    staff = make_staff()
    pid = "11111111-1111-1111-1111-111111111111"
    body = {"favorite_ids": ["x"], "patient_id": pid}
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "Patient") as P, \
         patch.object(favorites_api, "chart_review_note_type_id", return_value=None):
        P.objects.filter.return_value.exists.return_value = True
        [resp] = handler.post()
    assert resp.status_code == 400
    assert "chart review note type" in _body(resp)["error"]


def test_create_review_no_active_location(make_request, make_staff):
    staff = make_staff()
    pid = "11111111-1111-1111-1111-111111111111"
    body = {"favorite_ids": ["x"], "patient_id": pid}
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "Patient") as P, \
         patch.object(favorites_api, "chart_review_note_type_id", return_value="review-type-id"), \
         patch.object(favorites_api, "default_practice_location_id", return_value=None):
        P.objects.filter.return_value.exists.return_value = True
        [resp] = handler.post()
    assert resp.status_code == 400
    assert "practice location" in _body(resp)["error"]


def test_create_review_creates_note_and_stages_orders(make_request, make_staff, make_partner):
    staff = make_staff()
    partner = make_partner(tests=[("001", "Glucose"), ("002", "Lipid")])
    fav = _make_favorite(staff, partner, ["001", "002"])
    pid = "11111111-1111-1111-1111-111111111111"
    body = {"favorite_ids": [fav["id"]], "patient_id": pid}
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body=body))

    fake_cmd = MagicMock()
    fake_cmd.originate.return_value = "ORDER_EFFECT"
    fake_note = MagicMock()
    fake_note.create.return_value = "NOTE_EFFECT"
    with patch.object(favorites_api, "Patient") as P, \
         patch.object(favorites_api, "chart_review_note_type_id", return_value="review-type-id"), \
         patch.object(favorites_api, "default_practice_location_id", return_value="loc-id"), \
         patch.object(favorites_api, "NoteEffect", return_value=fake_note) as note_cls, \
         patch.object(favorites_api, "LabOrderCommand", return_value=fake_cmd) as cmd_cls:
        P.objects.filter.return_value.exists.return_value = True
        result = handler.post()

    data = _body(result[0])
    assert data["success"] is True
    assert data["chart_review_created"] is True
    assert len(data["inserted"]) == 1
    assert data["skipped"] == []
    # The note create effect comes first, then the staged lab order(s).
    assert result[1] == "NOTE_EFFECT"
    assert result[2] == "ORDER_EFFECT"

    # The note is created with the acting user as provider, plus the resolved
    # chart review type and default location.
    _, nkwargs = note_cls.call_args
    assert nkwargs["note_type_id"] == "review-type-id"
    assert nkwargs["practice_location_id"] == "loc-id"
    assert nkwargs["provider_id"] == str(staff.id)
    assert nkwargs["patient_id"] == pid
    assert nkwargs["datetime_of_service"] is not None
    assert str(nkwargs["instance_id"]) == data["note_uuid"]

    # The lab order is staged into the note being created in the same action.
    _, ckwargs = cmd_cls.call_args
    assert ckwargs["note_uuid"] == data["note_uuid"]
    assert ckwargs["tests_order_codes"] == ["001", "002"]
    assert ckwargs["ordering_provider_key"] == str(staff.id)


def test_create_review_skips_all_does_not_create_note(make_request, make_staff):
    staff = make_staff()
    pid = "11111111-1111-1111-1111-111111111111"
    # An unknown favorite id resolves to nothing, so there is nothing to stage.
    body = {"favorite_ids": ["does-not-exist"], "patient_id": pid}
    handler = _route(CreateChartReviewAPI, make_request(staff_id=str(staff.id), body=body))
    with patch.object(favorites_api, "Patient") as P, \
         patch.object(favorites_api, "chart_review_note_type_id", return_value="review-type-id"), \
         patch.object(favorites_api, "default_practice_location_id", return_value="loc-id"), \
         patch.object(favorites_api, "NoteEffect") as note_cls:
        P.objects.filter.return_value.exists.return_value = True
        result = handler.post()

    # No note effect emitted, only the JSON response.
    assert len(result) == 1
    data = _body(result[0])
    assert data["success"] is True
    assert data["chart_review_created"] is False
    assert len(data["skipped"]) == 1
    note_cls.assert_not_called()
