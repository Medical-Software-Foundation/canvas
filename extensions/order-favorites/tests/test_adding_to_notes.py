"""The note button and the add endpoint: which notes, which orders, and who is named on them."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from order_favorites.handlers.note_button import OrderFavoritesButton
from order_favorites.models import Favorite
from order_favorites.services.access import set_setting
from tests.conftest import make_api, reply
from tests.helpers import RX_DETAILS, effects_of, favorite, lab_details

NPI = "1234567893"


def button(note_id: Any) -> OrderFavoritesButton:
    handler = OrderFavoritesButton.__new__(OrderFavoritesButton)
    handler.event = SimpleNamespace(context={"note_id": note_id, "key": OrderFavoritesButton.BUTTON_KEY})
    return handler


def add(staff: Any, note: Any, ids: list[int]) -> tuple[int, dict[str, Any], list[Any]]:
    results = make_api(staff, body={"favorite_ids": ids}, path={"note_id": str(note.id)}).add_to_note()
    status, body = reply(results)
    return status, body, results


@pytest.mark.parametrize(
    ("category", "state", "shown"),
    [
        ("encounter", "NEW", True),
        ("review", "ULK", True),
        ("encounter", "BKD", True),
        ("appointment", "BKD", True),
        ("appointment", "RVT", True),
        ("appointment", "LKD", False),
        ("appointment", "CLD", False),
        ("encounter", "CVD", True),
        ("encounter", "LKD", False),
        ("review", "DLT", False),
        ("encounter", "CLD", False),
        ("encounter", "NSW", False),
        ("encounter", "SCH", False),
        ("letter", "NEW", False),
        ("message", "NEW", False),
    ],
)
def test_button_only_on_open_visit_and_chart_review_notes(make_note: Any, category: str, state: str, shown: bool) -> None:
    note = make_note(category=category, state=state)
    assert button(note.dbid).visible() is shown


def test_button_hidden_without_a_note() -> None:
    assert button(None).visible() is False


def test_button_opens_the_panel_for_the_clicked_note(make_note: Any) -> None:
    note = make_note()
    effects = button(note.dbid).handle()
    assert len(effects) == 1
    assert f"note_id={note.id}" in effects[0].payload
    assert "&v=" in effects[0].payload


def test_booked_appointment_note_receives_orders_for_precharting(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    me = make_staff(npi=NPI)
    partner = make_partner(tests=[("001", "Comprehensive panel")])
    note = make_note(category="appointment", state="BKD")
    status, _body, results = add(me, note, [favorite(me).dbid, favorite(me, kind="lab", details=lab_details(partner, ["001"])).dbid])
    assert status == 200
    assert effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")[0]["note_uuid"] == str(note.id)
    assert effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND")[0]["note_uuid"] == str(note.id)


def test_letters_and_messages_never_receive_orders(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    fav = favorite(me)
    for category in ("letter", "message"):
        status, body, results = add(me, make_note(category=category), [fav.dbid])
        assert status == 409
        assert effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND") == []


def test_note_locked_while_panel_open_adds_nothing(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    status, _body, results = add(me, make_note(state="LKD"), [favorite(me).dbid])
    assert status == 409
    assert effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND") == []


def test_care_manager_adding_to_provider_note_names_the_provider_as_prescriber(make_staff: Any, make_note: Any) -> None:
    provider = make_staff(first="Dana", npi=NPI)
    care_manager = make_staff(first="Casey")
    note = make_note(provider=provider)
    status, body, results = add(care_manager, note, [favorite(care_manager, shared=True).dbid])
    assert status == 200
    [rx] = effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")
    assert rx["prescriber_id"] == str(provider.id)
    assert rx["note_uuid"] == str(note.id)
    assert [a["id"] for a in body["added"]] == [Favorite.objects.get().dbid]


@pytest.mark.parametrize(("npi", "active"), [("", True), ("1111155556", True), (NPI, False)])
def test_prescriber_falls_back_to_the_adder_when_note_provider_cant_prescribe(make_staff: Any, make_note: Any, npi: str, active: bool) -> None:
    provider = make_staff(npi=npi, active=active)
    me = make_staff()
    _status, _body, results = add(me, make_note(provider=provider), [favorite(me).dbid])
    [rx] = effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")
    assert rx["prescriber_id"] == str(me.id)


def test_blank_prescription_fields_stay_blank_on_the_order(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    details = {**RX_DETAILS, "sig": "", "days_supply": None, "quantity": None, "unit": "", "representative_ndc": "", "ncpdp_quantity_qualifier_code": "", "refills": None}
    _status, _body, results = add(me, make_note(), [favorite(me, details=details).dbid])
    [rx] = effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")
    assert rx["fdb_code"] == "123456"
    assert rx.get("days_supply") is None and rx.get("quantity_to_dispense") is None and rx.get("refills") is None
    assert rx.get("type_to_dispense") is None
    assert rx.get("sig", "") == ""


def test_stale_lab_favorite_is_skipped_whole_while_others_are_added(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    me = make_staff()
    partner = make_partner(tests=[("001", "CMP")])
    stale = favorite(me, kind="lab", name="Thyroid recheck", details=lab_details(partner, ["001", "GONE"]))
    rx = favorite(me, name="Amox")
    status, body, results = add(me, make_note(), [stale.dbid, rx.dbid])
    assert status == 200
    assert effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND") == []
    assert len(effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND")) == 1
    assert body["skipped"] == [{"id": stale.dbid, "name": "Thyroid recheck", "kind": "lab", "shared": False, "reason": "stale", "lab": "Generic Lab", "stale": ["GONE"]}]


def test_lab_favorite_with_inactive_partner_is_skipped(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    me = make_staff()
    partner = make_partner(active=False, tests=[("001", "CMP")])
    fav = favorite(me, kind="lab", details=lab_details(partner, ["001"]))
    _status, body, results = add(me, make_note(), [fav.dbid])
    assert effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND") == []
    assert body["skipped"][0]["reason"] == "partner"


def test_lab_order_carries_tests_diagnoses_fasting_and_comment(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    me = make_staff()
    partner = make_partner(tests=[("001", "CMP"), ("002", "Lipid")])
    details = lab_details(partner, ["001", "002"], diagnoses=[{"code": "E119", "text": "Type 2"}], fasting=True, comment="Fasting 8h")
    _status, _body, results = add(me, make_note(), [favorite(me, kind="lab", details=details).dbid])
    [lab] = effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND")
    assert lab["tests_order_codes"] == ["001", "002"]
    assert lab["diagnosis_codes"] == ["E119"]
    assert lab["fasting_required"] is True
    assert lab["comment"] == "Fasting 8h"


def test_lab_ordering_provider_prefers_favorite_then_note_provider_then_adder(make_staff: Any, make_note: Any, make_partner: Any) -> None:
    saved = make_staff(first="Saved", npi=NPI)
    note_provider = make_staff(first="Note", npi=NPI)
    me = make_staff(first="Adder")
    partner = make_partner(tests=[("001", "CMP")])
    with_saved = favorite(me, kind="lab", details=lab_details(partner, ["001"], ordering_provider_id=str(saved.id)))
    without = favorite(me, kind="lab", details=lab_details(partner, ["001"]))

    _s, _b, results = add(me, make_note(provider=note_provider), [with_saved.dbid, without.dbid])
    first, second = effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND")
    assert first["ordering_provider_key"] == str(saved.id)
    assert second["ordering_provider_key"] == str(note_provider.id)

    _s, _b, results = add(me, make_note(), [without.dbid])
    [only] = effects_of(results, "ORIGINATE_LAB_ORDER_COMMAND")
    assert only["ordering_provider_key"] == str(me.id)


def test_someone_elses_personal_favorite_cant_be_added(make_staff: Any, make_note: Any) -> None:
    owner, me = make_staff(), make_staff()
    status, _body, results = add(me, make_note(), [favorite(owner).dbid])
    assert status == 404
    assert effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND") == []


def test_disabled_order_type_cant_be_added(make_staff: Any, make_note: Any) -> None:
    me = make_staff()
    set_setting("rx_enabled", False)
    status, _body, results = add(me, make_note(), [favorite(me).dbid])
    assert status == 404
    assert effects_of(results, "ORIGINATE_PRESCRIBE_COMMAND") == []
