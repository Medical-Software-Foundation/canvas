from __future__ import annotations

import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dot_phrases.handlers.api import DotPhrasesAPI

MODULE = "dot_phrases.handlers.api"
ADMIN_ID = "a" * 32
STAFF_ID = "b" * 32


def make_api(staff_id: str | None = STAFF_ID, body: dict[str, Any] | None = None, path: dict[str, str] | None = None, query: dict[str, str] | None = None) -> DotPhrasesAPI:
    handler = DotPhrasesAPI.__new__(DotPhrasesAPI)
    handler.secrets = {"ADMIN_TEAM": "Dot Phrase Admins"}
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
    request.json.return_value = body or {}
    request.path_params = path or {}
    request.query_params = query or {}
    handler.request = request
    return handler


def response(results: list[Any]) -> Any:
    return [r for r in results if hasattr(r, "status_code")][0]


def body_of(resp: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(resp.content)
    return data


def phrase(**kw: Any) -> Any:
    base = dict(dbid=1, code="fu2w", text="Follow up in 2 weeks.", scope="personal", owner_id=10, owner=None, use_in=None,
                rx_sig=False, rx_note_to_pharmacist=False, archived=False, uses=0, last_used_at=None)
    base.update(kw)
    return SimpleNamespace(**base, save=MagicMock())


@pytest.fixture
def db() -> Any:
    with (
        patch(f"{MODULE}.staff_dbid", side_effect=lambda sid: {STAFF_ID: 10, ADMIN_ID: 20}.get(sid or "")),
        patch(f"{MODULE}.practice_values", return_value={"after_hours_line": "(555) 010-2000"}),
        patch(f"{MODULE}.Phrase") as phrase_model,
        patch(f"{MODULE}.record_use") as record_use,
        patch(f"{MODULE}.favorite_ids", return_value=set()),
    ):
        phrase_model.objects.filter.return_value.first.return_value = None
        phrase_model.objects.filter.return_value.filter.return_value.first.return_value = None
        phrase_model.objects.filter.return_value.exclude.return_value.first.return_value = None
        phrase_model.objects.filter.return_value.filter.return_value.exclude.return_value.first.return_value = None
        phrase_model.objects.create.side_effect = lambda **kw: phrase(dbid=99, **kw)
        yield SimpleNamespace(phrase_model=phrase_model, record_use=record_use)


class TestCreatePhrase:
    def test_creates_a_personal_phrase_owned_by_the_signed_in_staff_member(self, db: Any) -> None:
        resp = response(make_api(body={"code": "fu2w", "text": "Follow up in 2 weeks.", "owner_id": 999}).create_phrase())
        assert resp.status_code == HTTPStatus.CREATED
        kwargs = db.phrase_model.objects.create.call_args.kwargs
        assert kwargs["owner_id"] == 10
        assert kwargs["scope"] == "personal"

    def test_personal_phrases_can_be_limited_to_certain_commands(self, db: Any) -> None:
        response(make_api(body={"code": "fu2w", "text": "x", "use_in": ["plan"]}).create_phrase())
        assert db.phrase_model.objects.create.call_args.kwargs["use_in"] == ["plan"]

    def test_no_use_in_means_every_note_command(self, db: Any) -> None:
        response(make_api(body={"code": "fu2w", "text": "x"}).create_phrase())
        assert db.phrase_model.objects.create.call_args.kwargs["use_in"] is None

    def test_personal_phrase_can_be_prescriptions_only(self, db: Any) -> None:
        response(make_api(body={"code": "taper", "text": "Take 1 tablet", "use_in": [], "rx_sig": True}).create_phrase())
        assert db.phrase_model.objects.create.call_args.kwargs["use_in"] == []

    def test_personal_prescriptions_only_needs_a_prescription_box(self, db: Any) -> None:
        resp = response(make_api(body={"code": "taper", "text": "Take 1 tablet", "use_in": []}).create_phrase())
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_practice_phrases_can_be_limited_to_certain_commands(self, db: Any) -> None:
        response(make_api(staff_id=ADMIN_ID, body={"code": "kneeinj", "text": "x", "scope": "practice", "use_in": ["perform", "plan"]}).create_phrase())
        assert db.phrase_model.objects.create.call_args.kwargs["use_in"] == ["plan", "perform"]

    def test_no_signed_in_staff_member_is_refused(self, db: Any) -> None:
        resp = response(make_api(staff_id=None, body={"code": "fu2w", "text": "x"}).create_phrase())
        assert resp.status_code == HTTPStatus.UNAUTHORIZED
        db.phrase_model.objects.create.assert_not_called()

    def test_practice_phrases_need_an_admin(self, db: Any) -> None:
        resp = response(make_api(body={"code": "fu2w", "text": "x", "scope": "practice"}).create_phrase())
        assert resp.status_code == HTTPStatus.FORBIDDEN
        resp = response(make_api(staff_id=ADMIN_ID, body={"code": "fu2w", "text": "x", "scope": "practice"}).create_phrase())
        assert resp.status_code == HTTPStatus.CREATED

    def test_admins_are_nobody_when_the_setting_is_empty(self, db: Any) -> None:
        api = make_api(staff_id=ADMIN_ID, body={"code": "fu2w", "text": "x", "scope": "practice"})
        api.secrets = {"ADMIN_TEAM": ""}
        assert response(api.create_phrase()).status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize(
        "body,message",
        [
            ({"code": "9abc", "text": "x"}, "Codes start with a lowercase letter"),
            ({"code": "fu2w", "text": ""}, "Write the text"),
            ({"code": "fu2w", "text": "Hi {frist_name}"}, "{frist_name} isn't a placeholder"),
            ({"code": "fu2w", "text": "x", "scope": "practice", "use_in": ["bogus"]}, "Use in has a command"),
            ({"code": "fu2w", "text": "x", "scope": "practice", "use_in": []}, "Pick at least one place"),
            ({"code": "gen", "text": "x" * 211, "use_in": [], "rx_note_to_pharmacist": True}, "over 210 characters"),
            ({"code": "sig", "text": "Take 1 tablet\ndaily", "use_in": [], "rx_sig": True}, "has a line break"),
        ],
    )
    def test_rejects_invalid_phrases(self, db: Any, body: dict[str, Any], message: str) -> None:
        resp = response(make_api(staff_id=ADMIN_ID if body.get("scope") == "practice" else "b" * 32, body=body).create_phrase())
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert message in body_of(resp)["error"]

    def test_duplicate_code_is_refused(self, db: Any) -> None:
        db.phrase_model.objects.filter.return_value.filter.return_value.first.return_value = phrase()
        resp = response(make_api(body={"code": "fu2w", "text": "x"}).create_phrase())
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        assert ".fu2w already exists" in body_of(resp)["error"]


class TestChangePhrase:
    def test_only_the_owner_can_change_a_personal_phrase(self, db: Any) -> None:
        db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = phrase(owner_id=55)
        resp = response(make_api(body={"code": "fu2w", "text": "x"}, path={"phrase_id": "1"}).update_phrase())
        assert resp.status_code == HTTPStatus.FORBIDDEN

    def test_owner_can_delete_their_phrase_and_its_stars_and_hides_go_with_it(self, db: Any) -> None:
        mine = phrase(owner_id=10, delete=MagicMock())
        db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = mine
        with patch(f"{MODULE}.PhraseFavorite") as fav, patch(f"{MODULE}.PhraseHidden") as hid:
            resp = response(make_api(path={"phrase_id": "1"}).delete_phrase())
        assert resp.status_code == HTTPStatus.OK
        assert body_of(resp) == {"deleted": "fu2w"}
        mine.delete.assert_called_once()
        fav.objects.filter.assert_called_once_with(phrase_id=1)
        hid.objects.filter.assert_called_once_with(phrase_id=1)

    def test_someone_else_cannot_delete_a_personal_phrase(self, db: Any) -> None:
        theirs = phrase(owner_id=55, delete=MagicMock())
        db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = theirs
        assert response(make_api(path={"phrase_id": "1"}).delete_phrase()).status_code == HTTPStatus.FORBIDDEN
        theirs.delete.assert_not_called()

    def test_only_admins_can_delete_a_practice_phrase(self, db: Any) -> None:
        shared = phrase(scope="practice", owner_id=20, delete=MagicMock())
        db.phrase_model.objects.filter.return_value.select_related.return_value.first.return_value = shared
        assert response(make_api(path={"phrase_id": "1"}).delete_phrase()).status_code == HTTPStatus.FORBIDDEN
        shared.delete.assert_not_called()
        with patch(f"{MODULE}.PhraseFavorite"), patch(f"{MODULE}.PhraseHidden"):
            assert response(make_api(staff_id=ADMIN_ID, path={"phrase_id": "1"}).delete_phrase()).status_code == HTTPStatus.OK
        shared.delete.assert_called_once()


class TestInsert:
    @pytest.fixture
    def note(self) -> Any:
        note = SimpleNamespace(id="note-uuid", dbid=5, patient=None, provider=None)
        with (
            patch(f"{MODULE}.Note") as note_model,
            patch(f"{MODULE}.CurrentNoteStateEvent") as state_model,
            patch(f"{MODULE}.placeholder_values", return_value={"first_name": "Jane"}),
            patch(f"{MODULE}.get_cache") as cache,
        ):
            note_model.objects.filter.return_value.select_related.return_value.first.return_value = note
            state_model.objects.filter.return_value.values_list.return_value.first.return_value = "NEW"
            yield SimpleNamespace(note=note, cache=cache)

    def test_adds_a_new_plan_with_answers_filled_in(self, db: Any, note: Any) -> None:
        knee = phrase(dbid=3, code="kneeinj", text="{pick side: right | left} knee injection for {first_name}.", use_in=["plan", "perform"])
        with patch(f"{MODULE}.usable_phrases", return_value={"kneeinj": knee}):
            results = make_api(body={"phrase_id": 3, "target": "plan", "answers": ["left"]}, path={"note_id": "note-uuid"}).insert()
        effect = results[0]
        data = json.loads(effect.payload)["data"]
        assert data["narrative"] == "left knee injection for Jane."
        db.record_use.assert_called_once_with([3])

    def test_refuses_a_command_the_phrase_is_not_set_up_for(self, db: Any, note: Any) -> None:
        knee = phrase(dbid=3, code="kneeinj", text="x", use_in=["perform"])
        with patch(f"{MODULE}.usable_phrases", return_value={"kneeinj": knee}):
            resp = response(make_api(body={"phrase_id": 3, "target": "hpi"}, path={"note_id": "note-uuid"}).insert())
        assert resp.status_code == HTTPStatus.BAD_REQUEST

    def test_unanswered_fill_ins_are_remembered_so_recording_is_blocked(self, db: Any, note: Any) -> None:
        knee = phrase(dbid=3, code="kneeinj", text="{pick side: right | left} knee.", use_in=None)
        with patch(f"{MODULE}.usable_phrases", return_value={"kneeinj": knee}):
            make_api(body={"phrase_id": 3, "target": "plan"}, path={"note_id": "note-uuid"}).insert()
        key, value = note.cache.return_value.set.call_args.args
        assert key.startswith("dot-phrases:leftovers:")
        assert value == ["[right / left]"]

    def test_fills_the_staged_prescriptions_sig(self, db: Any, note: Any) -> None:
        metf = phrase(dbid=1, code="metf500", text="Take 1 tablet by mouth twice daily with meals", use_in=[], rx_sig=True)
        staged = SimpleNamespace(id="rx-uuid", schema_key="prescribe")
        with patch(f"{MODULE}.usable_phrases", return_value={"metf500": metf}), patch(f"{MODULE}.Command") as command_model:
            command_model.objects.filter.return_value.order_by.return_value.first.return_value = staged
            results = make_api(body={"phrase_id": 1, "target": "sig"}, path={"note_id": "note-uuid"}).insert()
        data = json.loads(results[0].payload)["data"]
        assert data["sig"] == "Take 1 tablet by mouth twice daily with meals"

    def test_locked_note_is_refused(self, db: Any, note: Any) -> None:
        with patch(f"{MODULE}.CurrentNoteStateEvent") as state_model:
            state_model.objects.filter.return_value.values_list.return_value.first.return_value = "LKD"
            resp = response(make_api(body={"phrase_id": 1, "target": "plan"}, path={"note_id": "note-uuid"}).insert())
        assert resp.status_code == HTTPStatus.CONFLICT


class TestAdmin:
    def test_app_page_opens_for_staff_who_arent_admins(self, db: Any) -> None:
        with patch(f"{MODULE}.render_to_string", return_value="<p>app</p>"):
            assert response(make_api().admin_page()).status_code == HTTPStatus.OK

    def test_unknown_placeholder_message_fits_who_is_saving(self, db: Any) -> None:
        body = {"code": "fu2w", "text": "Hi {clinic_fax}"}
        staff = body_of(response(make_api(body=body).create_phrase()))["error"]
        admin = body_of(response(make_api(staff_id=ADMIN_ID, body=body).create_phrase()))["error"]
        assert staff == "{clinic_fax} isn't a placeholder. Fix the spelling, or ask your Dot Phrases admins to add it as practice info."
        assert admin == "{clinic_fax} isn't a placeholder. Add it on the Practice settings tab, or fix the spelling."

    def test_practice_value_names_are_checked(self, db: Any) -> None:
        with patch(f"{MODULE}.PracticeValue") as value_model:
            bad = response(make_api(staff_id=ADMIN_ID, body={"name": "Clinic Fax", "value": "1"}).save_value())
            taken = response(make_api(staff_id=ADMIN_ID, body={"name": "first_name", "value": "1"}).save_value())
            ok = response(make_api(staff_id=ADMIN_ID, body={"name": "clinic_fax", "value": "(555) 010-3000"}).save_value())
        assert bad.status_code == HTTPStatus.BAD_REQUEST
        assert taken.status_code == HTTPStatus.BAD_REQUEST
        assert ok.status_code == HTTPStatus.OK
        value_model.objects.update_or_create.assert_called_once_with(name="clinic_fax", defaults={"value": "(555) 010-3000"})

    def test_import_check_explains_each_line(self, db: Any) -> None:
        db.phrase_model.objects.filter.return_value.values_list.return_value = ["metf500"]
        text = "ckdplan, Plan, Recheck kidney function in 3 months.\n.metf500, Sig, Take 1 tablet\nbad code!, Plan, x\nacp, Any, With {first_name}, today."
        rows = body_of(response(make_api(staff_id=ADMIN_ID, body={"text": text}).import_check()))["rows"]
        assert [(r["code"], r["why"] == "") for r in rows] == [("ckdplan", True), ("metf500", False), ("bad code!", False), ("acp", True)]
        assert rows[0]["use_in"] == ["plan"]
        assert rows[3]["use_in"] is None
        assert rows[3]["text"] == "With {first_name}, today."

    def test_settings_need_an_admin(self, db: Any) -> None:
        assert response(make_api(body={"allow_copy_text": False}).save_settings()).status_code == HTTPStatus.FORBIDDEN


class TestHidePhrases:
    @pytest.fixture
    def hide_db(self, db: Any) -> Any:
        practice = phrase(dbid=5, code="insulin", scope="practice", owner_id=20)
        personal = phrase(dbid=6, code="fu2w", scope="personal", owner_id=10)
        with (
            patch(f"{MODULE}.usable_phrases", return_value={"insulin": practice, "fu2w": personal}),
            patch(f"{MODULE}.hidden_ids", return_value=set()) as hidden_ids,
            patch(f"{MODULE}.PhraseHidden") as hidden_model,
        ):
            # Only phrase 5 is a practice phrase.
            db.phrase_model.objects.filter.return_value.values_list.return_value = [5]
            yield SimpleNamespace(hidden_model=hidden_model, hidden_ids=hidden_ids, phrase_model=db.phrase_model)

    def test_hides_a_practice_phrase_for_the_signed_in_staff_member_only(self, hide_db: Any) -> None:
        resp = response(make_api(body={"phrase_ids": [5], "hidden": True}).hide_phrases())
        assert resp.status_code == HTTPStatus.OK
        rows = hide_db.hidden_model.objects.bulk_create.call_args.args[0]
        assert len(rows) == 1
        assert hide_db.hidden_model.call_args.kwargs == {"staff_id": 10, "phrase_id": 5}

    def test_personal_phrases_cannot_be_hidden(self, hide_db: Any) -> None:
        resp = response(make_api(body={"phrase_ids": [6], "hidden": True}).hide_phrases())
        assert resp.status_code == HTTPStatus.BAD_REQUEST
        hide_db.hidden_model.objects.bulk_create.assert_not_called()

    def test_practice_phrase_with_a_personal_copy_can_still_be_hidden(self, hide_db: Any) -> None:
        # The staff member's own .insulin replaces the practice one in their usable phrases.
        with patch(f"{MODULE}.usable_phrases", return_value={"insulin": phrase(dbid=6, code="insulin", scope="personal", owner_id=10)}):
            resp = response(make_api(body={"phrase_ids": [5], "hidden": True}).hide_phrases())
        assert body_of(resp)["phrase_ids"] == [5]
        assert hide_db.phrase_model.objects.filter.call_args.kwargs == {"scope": "practice", "archived": False, "dbid__in": [5]}

    def test_mixed_ids_hide_only_the_practice_ones(self, hide_db: Any) -> None:
        resp = response(make_api(body={"phrase_ids": [5, 6, 777], "hidden": True}).hide_phrases())
        assert body_of(resp)["phrase_ids"] == [5]

    def test_already_hidden_phrases_are_not_added_twice(self, hide_db: Any) -> None:
        hide_db.hidden_ids.return_value = {5}
        response(make_api(body={"phrase_ids": [5], "hidden": True}).hide_phrases())
        assert hide_db.hidden_model.objects.bulk_create.call_args.args[0] == []

    def test_showing_again_removes_the_hidden_rows(self, hide_db: Any) -> None:
        resp = response(make_api(body={"phrase_ids": [5], "hidden": False}).hide_phrases())
        assert body_of(resp) == {"phrase_ids": [5], "hidden": False}
        hide_db.hidden_model.objects.filter.assert_called_once_with(staff_id=10, phrase_id__in=[5])
        hide_db.hidden_model.objects.filter.return_value.delete.assert_called_once()

    def test_empty_or_bad_ids_are_refused(self, hide_db: Any) -> None:
        assert response(make_api(body={"phrase_ids": []}).hide_phrases()).status_code == HTTPStatus.BAD_REQUEST
        assert response(make_api(body={"phrase_ids": ["x"]}).hide_phrases()).status_code == HTTPStatus.BAD_REQUEST

    def test_no_signed_in_staff_member_is_refused(self, hide_db: Any) -> None:
        resp = response(make_api(staff_id=None, body={"phrase_ids": [5]}).hide_phrases())
        assert resp.status_code == HTTPStatus.UNAUTHORIZED
