from __future__ import annotations

import json

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
        patch(f"{MODULE}.placeholder_values", return_value={"after_hours_line": "(555) 010-2000"}) as values_for,
        patch(f"{MODULE}.Command") as command_model,
        patch(f"{MODULE}.hidden_ids", return_value={2}),
        patch(f"{MODULE}.note_label", return_value={"title": "RFV 1", "when": "", "provider": ""}) as label,
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
    assert data["note"] == {"title": "RFV 1", "when": "", "provider": ""}
    assert [m["name"] for m in data["menu_placeholders"]][:3] == ["first_name", "preferred_name", "last_name"]
    assert "mrn" not in [m["name"] for m in data["menu_placeholders"]]
    label.assert_called_once_with(note)
    # Only menu placeholders, practice info, and placeholders the phrases use are looked up and sent.
    needed = values_for.call_args.kwargs["needed"]
    assert {"first_name", "after_hours_line"} <= needed
    assert not {"mrn", "member_id", "group_number", "insurance"} & needed


def test_list_phrases_needs_a_signed_in_staff_member(db: Any) -> None:
    assert response(make_api(staff_id=None).list_phrases()).status_code == HTTPStatus.UNAUTHORIZED


def test_update_saves_the_changes(db: Any) -> None:
    mine = phrase(owner_id=10)
    db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = mine
    db.phrase_model.objects.filter.return_value.filter.return_value.exclude.return_value.first.return_value = None
    resp = response(make_api(body={"code": "fu3w", "text": "Follow up in 3 weeks.", "use_in": ["plan"]}, path={"phrase_id": "1"}).update_phrase())
    assert resp.status_code == HTTPStatus.OK
    assert (mine.code, mine.text, mine.use_in) == ("fu3w", "Follow up in 3 weeks.", ["plan"])
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
        assert response(make_api().shared_use_in_js()).headers["Content-Type"] == "application/javascript"
        assert response(make_api().shared_use_in_css()).headers["Content-Type"] == "text/css"
    assert render.call_args_list[0].args[1]["note_id"] == "n"
    assert render.call_args_list[0].args[1]["cache_bust"]


def test_admin_data_and_settings(db: Any) -> None:
    db.phrase_model.objects.filter.return_value.select_related.return_value.order_by.return_value = [phrase(scope="practice", text="Call {after_hours_line}.")]
    from tests.conftest import MemoryCache

    cache = MemoryCache()
    with patch(f"{MODULE}.hidden_ids", return_value=set()), patch(f"{MODULE}.PatientMetadata") as metadata, patch(f"{MODULE}.get_cache", return_value=cache):
        metadata.objects.order_by.return_value.values_list.return_value.distinct.return_value = ["program_name"]
        data = body_of(response(make_api(staff_id=ADMIN_ID).admin_data()))
        again = body_of(response(make_api(staff_id=ADMIN_ID).admin_data()))
    assert data["values"] == [{"name": "after_hours_line", "value": "(555) 010-2000", "used_in": 1}]
    assert data["is_admin"] is True
    assert data["metadata_keys"] == again["metadata_keys"] == ["program_name"]
    # The metadata key list is read once, then served from the cache.
    assert metadata.objects.order_by.call_count == 1
    assert [g["name"] for g in data["chart_groups"]] == ["Patient", "Visit", "Coverage"]
    assert "mrn" not in data["chart_enabled"]
    with patch(f"{MODULE}.set_setting") as set_setting:
        response(make_api(staff_id=ADMIN_ID, body={"allow_copy_text": False}).save_settings())
    set_setting.assert_called_once_with("allow_copy_text", False)


def test_app_data_splits_my_phrases_from_practice_phrases_for_any_staff_member(db: Any) -> None:
    rows = [
        phrase(dbid=1, code="fu2w", scope="personal", owner_id=10),
        phrase(dbid=2, code="kneehpi", scope="practice", owner_id=20),
        phrase(dbid=3, code="metf500", scope="practice", owner_id=20),
    ]
    db.phrase_model.objects.filter.return_value.select_related.return_value.order_by.return_value = rows
    with patch(f"{MODULE}.hidden_ids", return_value={3}):
        data = body_of(response(make_api().admin_data()))
    assert data["is_admin"] is False
    assert data["admin_team"] == "Dot Phrase Admins"
    assert [(p["code"], p["mine"]) for p in data["mine"]] == [("fu2w", True)]
    assert [(p["code"], p["hidden"]) for p in data["phrases"]] == [("kneehpi", False), ("metf500", True)]


def test_app_data_needs_a_signed_in_staff_member(db: Any) -> None:
    assert response(make_api(staff_id=None).admin_data()).status_code == HTTPStatus.UNAUTHORIZED


def test_chart_placeholder_choices_are_saved_in_list_order(db: Any) -> None:
    with patch(f"{MODULE}.set_setting") as set_setting:
        ok = response(make_api(staff_id=ADMIN_ID, body={"chart_placeholders": ["mrn", "first_name"]}).save_settings())
        bad = response(make_api(staff_id=ADMIN_ID, body={"chart_placeholders": ["shoe_size"]}).save_settings())
    assert ok.status_code == HTTPStatus.OK
    set_setting.assert_called_once_with("chart_placeholders", ["first_name", "mrn"])
    assert bad.status_code == HTTPStatus.BAD_REQUEST


def test_custom_placeholders_are_admin_only_and_checked(db: Any, practice_settings: Any) -> None:
    from tests.conftest import MemoryCache

    def fake_set(key: str, value: Any) -> None:
        practice_settings[key] = value

    cache = MemoryCache()
    cache.set("dot-phrases:metadata-keys", ["old_key"])
    with patch(f"{MODULE}.set_setting", side_effect=fake_set), patch(f"{MODULE}.get_cache", return_value=cache):
        assert response(make_api(body={"name": "program", "key": "program_name"}).save_custom_placeholder()).status_code == HTTPStatus.FORBIDDEN
        bad_name = response(make_api(staff_id=ADMIN_ID, body={"name": "Program!", "key": "program_name"}).save_custom_placeholder())
        chart = response(make_api(staff_id=ADMIN_ID, body={"name": "first_name", "key": "x"}).save_custom_placeholder())
        practice = response(make_api(staff_id=ADMIN_ID, body={"name": "after_hours_line", "key": "x"}).save_custom_placeholder())
        no_key = response(make_api(staff_id=ADMIN_ID, body={"name": "program", "key": ""}).save_custom_placeholder())
        ok = response(make_api(staff_id=ADMIN_ID, body={"name": "program", "key": "program_name"}).save_custom_placeholder())
        assert practice_settings["custom_placeholders"] == {"program": "program_name"}
        response(make_api(staff_id=ADMIN_ID, path={"name": "program"}).delete_custom_placeholder())
    assert [r.status_code for r in (bad_name, chart, practice, no_key, ok)] == [400, 400, 400, 400, 200]
    # Saving one refreshes the metadata key list next time the app loads.
    assert cache.get("dot-phrases:metadata-keys") is None
    assert practice_settings["custom_placeholders"] == {}


def test_metadata_key_list_says_when_it_is_cut_off(db: Any) -> None:
    from tests.conftest import MemoryCache

    db.phrase_model.objects.filter.return_value.select_related.return_value.order_by.return_value = []
    keys = [f"key_{i:03d}" for i in range(201)]
    with patch(f"{MODULE}.hidden_ids", return_value=set()), patch(f"{MODULE}.PatientMetadata") as metadata, patch(f"{MODULE}.get_cache", return_value=MemoryCache()):
        metadata.objects.order_by.return_value.values_list.return_value.distinct.return_value = keys
        data = body_of(response(make_api(staff_id=ADMIN_ID).admin_data()))
    assert len(data["metadata_keys"]) == 200
    assert data["metadata_keys_capped"] is True


class TestNoteValues:
    @pytest.fixture
    def note(self, db: Any) -> Any:
        found = SimpleNamespace(id="note-uuid", dbid=5, patient=SimpleNamespace(), provider=None)
        with patch(f"{MODULE}.Note") as note_model, patch(f"{MODULE}.placeholder_values", return_value={"last_visit": "09/02/2026 at 10:00 AM"}) as values_for:
            note_model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = found
            yield SimpleNamespace(values_for=values_for, model=note_model)

    def test_returns_only_the_placeholders_asked_for(self, note: Any) -> None:
        data = body_of(response(make_api(path={"note_id": "note-uuid"}, query={"names": "last_visit,shoe_size,LAST_VISIT"}).note_values()))
        assert data == {"values": {"last_visit": "09/02/2026 at 10:00 AM"}}
        assert note.values_for.call_args.kwargs["needed"] == {"last_visit"}

    def test_refuses_no_names_or_too_many(self, note: Any) -> None:
        assert response(make_api(path={"note_id": "note-uuid"}, query={"names": "shoe_size"}).note_values()).status_code == HTTPStatus.BAD_REQUEST

    def test_missing_note_or_staff_member(self, note: Any) -> None:
        note.model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = None
        assert response(make_api(path={"note_id": "x"}, query={"names": "mrn"}).note_values()).status_code == HTTPStatus.NOT_FOUND
        assert response(make_api(staff_id=None, path={"note_id": "x"}, query={"names": "mrn"}).note_values()).status_code == HTTPStatus.UNAUTHORIZED


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
        patch(f"{MODULE}.placeholder_values", return_value={}),
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


def test_copy_of_a_phrase_hidden_behind_a_personal_one_is_not_counted(db: Any) -> None:
    practice = phrase(dbid=3, scope="practice", owner_id=20)
    personal = phrase(dbid=1, owner_id=10)
    db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = practice
    with patch(f"{MODULE}.usable_phrases", return_value={"fu2w": personal}):
        assert response(make_api(path={"phrase_id": "3"}).phrase_used()).status_code == HTTPStatus.NOT_FOUND
    db.record_use.assert_not_called()


def test_import_keeps_a_fixed_copy_below_a_broken_line(db: Any) -> None:
    db.phrase_model.objects.filter.return_value.values_list.return_value = []
    rows = body_of(response(make_api(staff_id=ADMIN_ID, body={"text": "knee, Plan,\nknee, Plan, Knee exam normal."}).import_check()))["rows"]
    assert rows[0]["why"]
    assert rows[1]["why"] == ""


def test_insert_refuses_text_over_the_field_limit(db: Any) -> None:
    huge = phrase(dbid=4, code="huge", text="x" * 4001)
    note = SimpleNamespace(id="note-uuid", dbid=5, patient=None, provider=None)
    with (
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.CurrentNoteStateEvent") as state_model,
        patch(f"{MODULE}.usable_phrases", return_value={"huge": huge}),
        patch(f"{MODULE}.placeholder_values", return_value={}),
    ):
        note_model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = note
        state_model.objects.filter.return_value.values_list.return_value.first.return_value = "NEW"
        resp = response(make_api(body={"phrase_id": 4, "target": "instruct"}, path={"note_id": "note-uuid"}).insert())
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert "limit is 4,000" in body_of(resp)["error"]


def test_insert_into_sig_fills_placeholders_and_remembers_fill_ins(db: Any) -> None:
    taper = phrase(dbid=6, code="taper", text="Take {blank count} tablets daily for {first_name}", use_in=[], rx_sig=True)
    note = SimpleNamespace(id="note-uuid", dbid=5, patient=None, provider=None)
    rx = SimpleNamespace(id="rx-uuid", schema_key="prescribe")
    cache: dict[str, Any] = {}
    fake_cache = SimpleNamespace(get=lambda k, d=None: cache.get(k, d), set=lambda k, v, timeout_seconds=None: cache.__setitem__(k, v))
    with (
        patch(f"{MODULE}.Note") as note_model,
        patch(f"{MODULE}.CurrentNoteStateEvent") as state_model,
        patch(f"{MODULE}.usable_phrases", return_value={"taper": taper}),
        patch(f"{MODULE}.Command") as command_model,
        patch(f"{MODULE}.placeholder_values", return_value={"first_name": "Jane"}),
        patch(f"{MODULE}.get_cache", return_value=fake_cache),
    ):
        note_model.objects.filter.return_value.select_related.return_value.defer.return_value.first.return_value = note
        state_model.objects.filter.return_value.values_list.return_value.first.return_value = "NEW"
        command_model.objects.filter.return_value.order_by.return_value.first.return_value = rx
        results = make_api(body={"phrase_id": 6, "target": "sig", "answers": []}, path={"note_id": "note-uuid"}).insert()
    edit = [r for r in results if not hasattr(r, "status_code")][0]
    assert json.loads(edit.payload)["data"]["sig"] == "Take [count] tablets daily for Jane"
    assert cache["dot-phrases:leftovers:rx-uuid"] == ["[count]"]
