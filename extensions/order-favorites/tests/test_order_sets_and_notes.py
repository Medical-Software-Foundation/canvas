"""Order sets (several favorites added together) and the list of other notes for Change."""

from __future__ import annotations

from typing import Any

import pytest

from order_favorites.models import Favorite, FavoritesAdmin
from order_favorites.services.access import set_setting
from order_favorites.services.favorites import Invalid, clean_favorite
from tests.conftest import make_api, reply
from tests.helpers import effects_of, favorite, lab_details


def a_set(owner: Any, items: list[int], shared: bool = False, name: str = "Set") -> Favorite:
    created: Favorite = Favorite.objects.create(kind="set", name=name, shared=shared, owner_id=owner.dbid, details={"items": items})
    return created


def add(staff: Any, note: Any, ids: list[int]) -> tuple[int, dict[str, Any], list[Any]]:
    results = make_api(staff, body={"favorite_ids": ids}, path={"note_id": str(note.id)}).add_to_note()
    status, body = reply(results)
    return status, body, results


# ---------- what a set may contain ----------

def test_personal_set_may_hold_own_and_practice_favorites(make_staff: Any) -> None:
    me = make_staff()
    mine, prac = favorite(me), favorite(make_staff(), shared=True)
    kind, name, details = clean_favorite({"kind": "set", "name": "Visit", "items": [mine.dbid, prac.dbid, mine.dbid]}, owner=me.dbid)
    assert (kind, name, details) == ("set", "Visit", {"items": [mine.dbid, prac.dbid]})


def test_personal_set_cant_hold_someone_elses_personal_favorite(make_staff: Any) -> None:
    me, other = make_staff(), make_staff()
    with pytest.raises(Invalid, match="Select favorites from the list."):
        clean_favorite({"kind": "set", "name": "x", "items": [favorite(other).dbid]}, owner=me.dbid)


def test_practice_set_can_only_hold_practice_favorites(make_staff: Any) -> None:
    me = make_staff()
    with pytest.raises(Invalid, match="A practice order set can only include practice favorites."):
        clean_favorite({"kind": "set", "name": "x", "items": [favorite(me).dbid]}, owner=me.dbid, shared=True)


def test_set_needs_favorites_and_cant_hold_another_set(make_staff: Any) -> None:
    me = make_staff()
    with pytest.raises(Invalid, match="Select at least one favorite"):
        clean_favorite({"kind": "set", "name": "x", "items": []}, owner=me.dbid)
    inner = a_set(me, [favorite(me).dbid])
    with pytest.raises(Invalid, match="Select favorites from the list."):
        clean_favorite({"kind": "set", "name": "x", "items": [inner.dbid]}, owner=me.dbid)


def test_panel_saves_a_personal_set_and_admins_save_practice_sets(make_staff: Any) -> None:
    me = make_staff()
    prac = favorite(make_staff(), shared=True)
    status, body = reply(make_api(me, body={"kind": "set", "name": "Mine", "items": [prac.dbid]}).create_favorite())
    assert (status, body["favorite"]["shared"], body["favorite"]["items"]) == (201, False, [prac.dbid])
    FavoritesAdmin.objects.create(staff_id=me.dbid)
    status, body = reply(make_api(me, body={"kind": "set", "name": "Practice", "items": [prac.dbid]}).admin_create())
    assert (status, body["favorite"]["shared"]) == (201, True)


# ---------- adding a set ----------

def test_adding_a_set_adds_every_order_once(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    me = make_staff()
    partner = make_partner(tests=[("001", "CMP")])
    rx = favorite(me, name="Statin")
    lab = favorite(me, kind="lab", name="Panel", details=lab_details(partner, ["001"]))
    bundle = a_set(me, [lab.dbid, rx.dbid])
    status, body, results = add(me, make_note(), [bundle.dbid, rx.dbid])
    assert status == 200
    assert [a["name"] for a in body["added"]] == ["Panel", "Statin"]
    assert len(effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")) == 1
    assert len(effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND")) == 1


def test_set_adds_only_orders_of_types_still_turned_on(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    me = make_staff()
    partner = make_partner(tests=[("001", "CMP")])
    bundle = a_set(me, [favorite(me).dbid, favorite(me, kind="lab", details=lab_details(partner, ["001"])).dbid])
    set_setting("lab_enabled", False)
    _s, body, results = add(me, make_note(), [bundle.dbid])
    assert len(effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")) == 1
    assert effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND") == []


def test_deleted_favorite_drops_out_of_a_set(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    keep, gone = favorite(me, name="Keep"), favorite(me, name="Gone")
    bundle = a_set(me, [keep.dbid, gone.dbid])
    gone.delete()
    _s, body, _r = add(me, make_note(), [bundle.dbid])
    assert [a["name"] for a in body["added"]] == ["Keep"]


def test_sets_switched_off_cant_be_listed_or_added(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    bundle = a_set(me, [favorite(me).dbid])
    set_setting("set_enabled", False)
    note = make_note()
    _s, data = reply(make_api(me, query={"note_id": str(note.id)}).panel_data())
    assert data["sets_enabled"] is False
    assert all(f["kind"] != "set" for f in data["favorites"])
    status, _b, _r = add(me, note, [bundle.dbid])
    assert status == 404
    status, _ = reply(make_api(me, body={"kind": "set", "name": "x", "items": [favorite(me).dbid]}).create_favorite())
    assert status == 400


def test_someone_elses_personal_set_cant_be_added(make_staff: Any, make_note: Any) -> None:
    owner, me = make_staff(), make_staff()
    bundle = a_set(owner, [favorite(owner, shared=True).dbid])
    status, _b, results = add(me, make_note(), [bundle.dbid])
    assert status == 404
    assert effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND") == []


def test_turning_sets_off_is_a_setting_of_its_own(make_staff: Any) -> None:
    admin = make_staff()
    FavoritesAdmin.objects.create(staff_id=admin.dbid)
    status, body = reply(make_api(admin, body={"set_enabled": False}).admin_settings())
    assert (status, body["settings"]) == (200, {"rx_enabled": True, "lab_enabled": True, "set_enabled": False})


# ---------- Change: the patient's other open notes ----------

def test_other_notes_are_the_patients_open_visit_and_review_notes(make_staff: Any, make_note: Any) -> None:
    from canvas_sdk.v1.data import Patient

    me = make_staff()
    patient = Patient.objects.create(first_name="Pat", last_name="Zztest", birth_date="1990-01-01")
    other_patient = Patient.objects.create(first_name="Sam", last_name="Zztest", birth_date="1990-01-01")
    clicked = make_note(title="Clicked")
    review = make_note(category="review", title="Review")
    locked = make_note(state="LKD", title="Locked")
    letter = make_note(category="letter", title="Letter")
    elsewhere = make_note(title="Other patient")
    for n in (clicked, review, locked, letter):
        n.patient = patient
        n.save()
    elsewhere.patient = other_patient
    elsewhere.save()
    status, body = reply(make_api(me, path={"note_id": str(clicked.id)}).other_notes())
    assert status == 200
    assert {n["title"]: n["clicked"] for n in body["notes"]} == {"Clicked": True, "Review": False}
    assert body["total"] == 2


def test_other_notes_show_the_20_most_recent_and_count_them_all(make_staff: Any, make_note: Any) -> None:
    from canvas_sdk.v1.data import Patient

    patient = Patient.objects.create(first_name="Pat", last_name="Zztest", birth_date="1990-01-01")
    notes = [make_note(title=f"Visit {i}") for i in range(23)]
    for n in notes:
        n.patient = patient
        n.save()
    _s, body = reply(make_api(make_staff(), path={"note_id": str(notes[0].id)}).other_notes())
    assert (len(body["notes"]), body["total"]) == (20, 23)


def test_other_notes_still_list_after_the_clicked_note_is_locked(make_staff: Any, make_note: Any) -> None:
    from canvas_sdk.v1.data import Patient

    patient = Patient.objects.create(first_name="Pat", last_name="Zztest", birth_date="1990-01-01")
    locked, open_note = make_note(state="LKD", title="Locked"), make_note(title="Open")
    for n in (locked, open_note):
        n.patient = patient
        n.save()
    _s, body = reply(make_api(make_staff(), path={"note_id": str(locked.id)}).other_notes())
    assert [n["title"] for n in body["notes"]] == ["Open"]


def test_each_listed_note_links_to_itself_in_the_chart_by_dbid(make_staff: Any, make_note: Any) -> None:
    from canvas_sdk.v1.data import Patient

    patient = Patient.objects.create(first_name="Pat", last_name="Zztest", birth_date="1990-01-01")
    first, second = make_note(title="One"), make_note(title="Two")
    for n in (first, second):
        n.patient = patient
        n.save()
    _s, body = reply(make_api(make_staff(), path={"note_id": str(first.id)}).other_notes())
    urls = {n["title"]: n["url"] for n in body["notes"]}
    assert urls == {"One": f"/patient/{patient.id}?noteId={first.dbid}", "Two": f"/patient/{patient.id}?noteId={second.dbid}"}


def test_note_without_a_patient_has_no_link(make_note: Any) -> None:
    from order_favorites.services.notes import note_label

    assert note_label(make_note(title="Orphan"))["url"] == ""


def test_adding_to_a_different_open_note_of_the_patient(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    other = make_note(title="Telehealth")
    _s, body, results = add(me, other, [favorite(me).dbid])
    [rx] = effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")
    assert rx["note_uuid"] == str(other.id)
    assert body["note"]["title"] == "Telehealth"


# ---------- note titles follow the note heading ----------

def test_note_title_is_the_reason_for_visit_then_the_title_then_the_type(make_staff: Any, make_note: Any) -> None:
    from canvas_sdk.v1.data import Patient
    from canvas_sdk.v1.data.reason_for_visit import ReasonForVisit, ReasonForVisitCoding
    from canvas_sdk.v1.data.user import CanvasUser

    from order_favorites.services.notes import note_label, reason_for_visit_titles

    user = CanvasUser.objects.create(email="doc@example.org")
    patient = Patient.objects.create(first_name="Pat", last_name="Zztest", birth_date="1990-01-01")
    coded, typed, draft, titled, plain = (make_note(title=t) for t in ("", "", "", "Follow-up", ""))
    for n in (coded, typed, draft, titled, plain):
        n.patient = patient
        n.save()
    rfv = ReasonForVisit.objects.create(patient=patient, note=coded, committer=user, narrative_json="typed comment")
    ReasonForVisitCoding.objects.create(reason_for_visit=rfv, display="Annual exam", code="1", system="x")
    ReasonForVisit.objects.create(patient=patient, note=coded, committer=user, narrative_json="second reason")
    ReasonForVisit.objects.create(patient=patient, note=typed, committer=user, narrative_json="Knee pain")
    ReasonForVisit.objects.create(patient=patient, note=draft, narrative_json="Not recorded yet")

    titles = reason_for_visit_titles([coded, typed, draft, titled, plain])
    assert titles == {coded.dbid: "Annual exam", typed.dbid: "Knee pain"}
    assert [note_label(n)["title"] for n in (coded, typed, draft, titled, plain)] == ["Annual exam", "Knee pain", "Encounter", "Follow-up", "Encounter"]
