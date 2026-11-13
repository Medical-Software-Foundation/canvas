"""Tests for replacing the native footer Sign with Co-sign for the supervisor who owes one."""

import json
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.v1.data.note import NoteStates

from supervisor_cosign.helpers import viewer_cosign
from supervisor_cosign.protocols.cosign_button import CoSignButton
from supervisor_cosign.protocols.cosign_footer import CoSignAmendButton, CoSignFooterConfiguration

FOOTER = "supervisor_cosign.protocols.cosign_footer"
BUTTON = "supervisor_cosign.protocols.cosign_button"
HELPER = "supervisor_cosign.helpers.viewer_cosign"


def make_event(name: str, context: dict | None = None, target_id: str = "note-uuid", actor_id: str = "92"):
    event = MagicMock()
    event.name = name
    event.context = context or {}
    event.target.id = target_id
    event.actor.id = actor_id
    return event


def make(cls, event):
    handler = cls.__new__(cls)
    handler.event = event
    handler.secrets = {}
    handler.environment = {}
    return handler


# viewer_owes_cosign


def owes(record_exists: bool = True, note_closed: bool = True):
    with (
        patch(f"{HELPER}.Staff") as staff_model,
        patch(f"{HELPER}.CoSignRecord") as record_model,
        patch(f"{HELPER}.CurrentNoteStateEvent") as state_model,
    ):
        staff_model.objects.filter.return_value.values_list.return_value.first.return_value = "supervisor"
        record_model.objects.filter.return_value.exists.return_value = record_exists
        state_model.objects.filter.return_value.exists.return_value = note_closed
        result = viewer_cosign.viewer_owes_cosign("note-uuid", "92")
    return result, staff_model, record_model, state_model


def test_viewer_owes_cosign_filters_on_viewer_staff_pending_and_closed_note():
    result, staff_model, record_model, state_model = owes()

    assert result is True
    staff_model.objects.filter.assert_called_once_with(user__dbid="92")
    record_model.objects.filter.assert_called_once_with(
        note_id="note-uuid", supervisor_id="supervisor", status="pending"
    )
    state_model.objects.filter.assert_called_once_with(
        note__id="note-uuid", state__in=(NoteStates.LOCKED, NoteStates.SIGNED)
    )


def test_unlocked_note_with_pending_record_keeps_native_footer():
    result, *_ = owes(note_closed=False)
    assert result is False


def test_no_pending_record_skips_the_state_lookup():
    result, _, _, state_model = owes(record_exists=False)
    assert result is False
    state_model.objects.filter.assert_not_called()


def test_viewer_without_staff_row_owes_nothing():
    with (
        patch(f"{HELPER}.Staff") as staff_model,
        patch(f"{HELPER}.CoSignRecord") as record_model,
    ):
        staff_model.objects.filter.return_value.values_list.return_value.first.return_value = None
        assert viewer_cosign.viewer_owes_cosign("note-uuid", "92") is False
    record_model.objects.filter.assert_not_called()


@pytest.mark.parametrize("note_uuid,actor", [(None, "92"), ("note-uuid", None), ("", "92")])
def test_missing_note_or_actor_owes_nothing(note_uuid, actor):
    with patch(f"{HELPER}.CoSignRecord") as record_model:
        assert viewer_cosign.viewer_owes_cosign(note_uuid, actor) is False
    record_model.objects.filter.assert_not_called()


# CoSignFooterConfiguration


def test_footer_configuration_hides_native_buttons_for_owing_supervisor():
    event = make_event("NOTE_FOOTER__GET_CONFIGURATION", target_id="note-uuid", actor_id="92")
    with patch(f"{FOOTER}.viewer_owes_cosign", return_value=True) as owes:
        effects = make(CoSignFooterConfiguration, event).compute()

    owes.assert_called_once_with("note-uuid", "92")
    assert len(effects) == 1
    assert effects[0].type == EffectType.NOTE_FOOTER__CONFIGURATION
    assert json.loads(effects[0].payload)["data"]["hide_default_state_buttons"] is True


def test_footer_configuration_leaves_everyone_else_alone():
    event = make_event("NOTE_FOOTER__GET_CONFIGURATION")
    with patch(f"{FOOTER}.viewer_owes_cosign", return_value=False):
        assert make(CoSignFooterConfiguration, event).compute() == []


# CoSignButton


def test_footer_cosign_button_shows_for_owing_supervisor():
    event = make_event("SHOW_NOTE_FOOTER_BUTTON", context={"note_id": 7})
    handler = make(CoSignButton, event)
    with (
        patch.object(CoSignButton, "_note_uuid", return_value="note-uuid"),
        patch(f"{BUTTON}.viewer_owes_cosign", return_value=True) as owes,
    ):
        effects = handler.compute()

    owes.assert_called_once_with("note-uuid", "92")
    assert len(effects) == 1
    payload = json.loads(effects[0].payload)["data"]
    assert payload["key"] == "COSIGN_FOOTER_BUTTON"
    assert payload["title"] == "Co-sign"
    assert payload["priority"] == 0


def test_footer_cosign_button_hidden_for_everyone_else():
    event = make_event("SHOW_NOTE_FOOTER_BUTTON", context={"note_id": 7})
    with (
        patch.object(CoSignButton, "_note_uuid", return_value="note-uuid"),
        patch(f"{BUTTON}.viewer_owes_cosign", return_value=False),
    ):
        assert make(CoSignButton, event).compute() == []


def test_footer_cosign_click_opens_the_attestation_modal():
    event = make_event("ACTION_BUTTON_CLICKED", context={"note_id": 7, "key": "COSIGN_FOOTER_BUTTON"})
    handler = make(CoSignButton, event)
    with patch.object(CoSignButton, "handle", return_value=["modal"]) as handle:
        assert handler.compute() == ["modal"]
    handle.assert_called_once()


def test_another_buttons_click_is_not_handled_by_cosign_button():
    event = make_event("ACTION_BUTTON_CLICKED", context={"note_id": 7, "key": "COSIGN_AMEND_BUTTON"})
    with patch.object(CoSignButton, "handle") as handle:
        assert make(CoSignButton, event).compute() == []
    handle.assert_not_called()


# CoSignAmendButton


def amend_effects(state: NoteStates, sig_required: bool, owes: bool):
    event = make_event("SHOW_NOTE_FOOTER_BUTTON", context={"note_id": 7})
    handler = make(CoSignAmendButton, event)
    handler.__dict__["_note_context"] = (state, sig_required, "encounter")
    with (
        patch(f"{FOOTER}.note_uuid_for_dbid", return_value="note-uuid"),
        patch(f"{FOOTER}.viewer_owes_cosign", return_value=owes),
    ):
        return handler.compute()


def test_amend_button_on_signed_note_reads_amend_and_sits_after_cosign():
    effects = amend_effects(NoteStates.SIGNED, sig_required=True, owes=True)
    payload = json.loads(effects[0].payload)["data"]
    assert payload["key"] == "COSIGN_AMEND_BUTTON"
    assert payload["title"] == "Amend"
    assert payload["priority"] == 1


def test_amend_button_on_locked_note_reads_unlock():
    effects = amend_effects(NoteStates.LOCKED, sig_required=True, owes=True)
    assert json.loads(effects[0].payload)["data"]["title"] == "Unlock"


def test_amend_button_hidden_when_viewer_owes_nothing():
    assert amend_effects(NoteStates.SIGNED, sig_required=True, owes=False) == []


def test_amend_button_hidden_when_unlock_is_not_a_valid_transition():
    assert amend_effects(NoteStates.NEW, sig_required=True, owes=True) == []
