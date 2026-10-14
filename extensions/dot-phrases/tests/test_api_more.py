from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from tests.test_api import ADMIN_ID, MODULE, body_of, make_api, phrase, response


@pytest.fixture
def db() -> Any:
    with (
        patch(f"{MODULE}.staff_dbid", side_effect=lambda sid: {"b" * 32: 10, ADMIN_ID: 20}.get(sid or "")),
        patch(f"{MODULE}.practice_values", return_value={"after_hours_line": "(555) 010-2000"}),
        patch(f"{MODULE}.Phrase") as phrase_model,
        patch(f"{MODULE}.record_use") as record_use,
        patch(f"{MODULE}.favorite_ids", return_value={1}),
        patch(f"{MODULE}.get_setting", return_value=True),
    ):
        yield SimpleNamespace(phrase_model=phrase_model, record_use=record_use)


def test_list_phrases_returns_previews_favorites_and_prescription_targets(db: Any) -> None:
    note = SimpleNamespace(id="note-uuid", patient=None, provider=None)
    rows = {"fu2w": phrase(dbid=1, owner_id=10, text="Call {after_hours_line}."), "dmed": phrase(dbid=2, code="dmed", scope="practice", owner_id=20)}
    with (
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.usable_phrases", return_value=rows),
        patch(f"{MODULE}.placeholder_values", return_value={"after_hours_line": "(555) 010-2000"}),
        patch(f"{MODULE}.Command") as command_model,
        patch(f"{MODULE}.hidden_ids", return_value={2}),
    ):
        note_model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = note
        command_model.objects.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(id="rx")
        data = body_of(response(make_api(query={"note_id": "note-uuid"}).list_phrases()))
    by_code = {p["code"]: p for p in data["phrases"]}
    assert by_code["fu2w"]["preview"] == "Call (555) 010-2000."
    assert by_code["fu2w"]["mine"] is True and by_code["fu2w"]["favorite"] is True
    assert by_code["dmed"]["mine"] is False
    assert by_code["dmed"]["hidden"] is True and by_code["fu2w"]["hidden"] is False
    assert "archived" not in data
    assert data["rx_targets"] == ["sig", "note_to_pharmacist"]
    assert data["allow_copy_text"] is True
    assert data["is_admin"] is False
    assert data["admin_team"] == "Dot Phrase Admins"


def test_list_phrases_needs_a_signed_in_staff_member(db: Any) -> None:
    assert response(make_api(staff_id=None).list_phrases()).status_code == HTTPStatus.UNAUTHORIZED


def test_update_saves_the_changes(db: Any) -> None:
    mine = phrase(owner_id=10)
    db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = mine
    db.phrase_model.objects.filter.return_value.filter.return_value.exclude.return_value.first.return_value = None
    resp = response(make_api(body={"code": "fu3w", "text": "Follow up in 3 weeks.", "use_in": ["plan"]}, path={"phrase_id": "1"}).update_phrase())
    assert resp.status_code == HTTPStatus.OK
    assert (mine.code, mine.text, mine.use_in) == ("fu3w", "Follow up in 3 weeks.", None)
    mine.save.assert_called_once()


def test_bad_phrase_id_is_not_found(db: Any) -> None:
    assert response(make_api(path={"phrase_id": "abc"}).delete_phrase()).status_code == HTTPStatus.NOT_FOUND


def test_favorite_toggles(db: Any) -> None:
    fu = phrase(dbid=1, owner_id=10)
    db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = fu
    with patch(f"{MODULE}.usable_phrases", return_value={"fu2w": fu}), patch(f"{MODULE}.PhraseFavorite") as fav:
        fav.objects.filter.return_value.exists.return_value = False
        assert body_of(response(make_api(path={"phrase_id": "1"}).toggle_favorite())) == {"favorite": True}
        fav.objects.create.assert_called_once_with(staff_id=10, phrase_id=1)
        fav.objects.filter.return_value.exists.return_value = True
        assert body_of(response(make_api(path={"phrase_id": "1"}).toggle_favorite())) == {"favorite": False}


def test_copy_counts_as_a_use(db: Any) -> None:
    fu = phrase(dbid=1, owner_id=10)
    db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = fu
    with patch(f"{MODULE}.usable_phrases", return_value={"fu2w": fu}):
        assert response(make_api(path={"phrase_id": "1"}).phrase_used()).status_code == HTTPStatus.OK
    db.record_use.assert_called_once_with([1])


def test_pages_and_assets_render(db: Any) -> None:
    with patch(f"{MODULE}.render_to_string", return_value="body") as render:
        assert response(make_api(query={"note_id": "n"}).panel_page()).status_code == HTTPStatus.OK
        assert response(make_api().panel_js()).headers["Content-Type"] == "application/javascript"
        assert response(make_api().panel_css()).headers["Content-Type"] == "text/css"
        assert response(make_api(staff_id=ADMIN_ID).admin_page()).status_code == HTTPStatus.OK
        assert response(make_api().admin_js()).headers["Content-Type"] == "application/javascript"
        assert response(make_api().admin_css()).headers["Content-Type"] == "text/css"
        assert response(make_api().icon()).headers["Content-Type"] == "image/svg+xml"
    assert render.call_args_list[0].args[1]["note_id"] == "n"
    assert render.call_args_list[0].args[1]["cache_bust"]


def test_admin_data_and_settings(db: Any) -> None:
    db.phrase_model.objects.filter.return_value.select_related.return_value.order_by.return_value = [phrase(scope="practice", text="Call {after_hours_line}.")]
    data = body_of(response(make_api(staff_id=ADMIN_ID).admin_data()))
    assert data["values"] == [{"name": "after_hours_line", "value": "(555) 010-2000", "used_in": 1}]
    assert response(make_api().admin_data()).status_code == HTTPStatus.FORBIDDEN
    with patch(f"{MODULE}.set_setting") as set_setting:
        response(make_api(staff_id=ADMIN_ID, body={"allow_copy_text": False}).save_settings())
    set_setting.assert_called_once_with("allow_copy_text", False)


def test_delete_value_needs_an_admin(db: Any) -> None:
    with patch(f"{MODULE}.PracticeValue") as value_model:
        assert response(make_api(path={"name": "x"}).delete_value()).status_code == HTTPStatus.FORBIDDEN
        assert response(make_api(staff_id=ADMIN_ID, path={"name": "clinic_fax"}).delete_value()).status_code == HTTPStatus.OK
    value_model.objects.filter.assert_called_once_with(name="clinic_fax")


def test_import_creates_only_the_lines_that_passed(db: Any) -> None:
    db.phrase_model.objects.filter.return_value.values_list.return_value = []
    db.phrase_model.side_effect = lambda **kw: SimpleNamespace(**kw)
    text = "ckdplan, Plan, Recheck kidney function.\nbad!, Plan, x\nmetf500, Sig, Take 1 tablet\nmetf500, Sig, Take 1 tablet"
    data = body_of(response(make_api(staff_id=ADMIN_ID, body={"text": text}).import_phrases()))
    assert data == {"imported": 2}
    created = db.phrase_model.objects.bulk_create.call_args.args[0]
    assert [(c.code, c.scope, c.owner_id, c.rx_sig) for c in created] == [("ckdplan", "practice", 20, False), ("metf500", "practice", 20, True)]


def test_import_needs_an_admin(db: Any) -> None:
    assert response(make_api(body={"text": "a, Plan, b"}).import_phrases()).status_code == HTTPStatus.FORBIDDEN
    assert response(make_api(body={"text": "a, Plan, b"}).import_check()).status_code == HTTPStatus.FORBIDDEN


def test_insert_into_sig_needs_a_waiting_prescription(db: Any) -> None:
    metf = phrase(dbid=1, code="metf500", text="Take 1 tablet", use_in=[], rx_sig=True)
    note = SimpleNamespace(id="note-uuid", dbid=5, patient=None, provider=None)
    with (
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.CurrentNoteStateEvent") as state_model,
        patch(f"{MODULE}.usable_phrases", return_value={"metf500": metf}),
        patch(f"{MODULE}.Command") as command_model,
    ):
        note_model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = note
        state_model.objects.filter.return_value.values_list.return_value.first.return_value = "NEW"
        command_model.objects.filter.return_value.order_by.return_value.first.return_value = None
        resp = response(make_api(body={"phrase_id": 1, "target": "sig"}, path={"note_id": "note-uuid"}).insert())
    assert resp.status_code == HTTPStatus.CONFLICT




def test_favorite_refuses_someone_elses_phrase_with_the_same_code(db: Any) -> None:
    mine = phrase(dbid=1, owner_id=10)
    theirs = phrase(dbid=2, owner_id=55)
    db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = theirs
    with patch(f"{MODULE}.usable_phrases", return_value={"fu2w": mine}), patch(f"{MODULE}.PhraseFavorite") as fav:
        resp = response(make_api(path={"phrase_id": "2"}).toggle_favorite())
    assert resp.status_code == HTTPStatus.NOT_FOUND
    fav.objects.create.assert_not_called()
