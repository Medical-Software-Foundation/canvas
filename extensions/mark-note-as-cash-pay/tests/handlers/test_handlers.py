"""Behavior tests for the dropdown buttons and the routing handler."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType

from mark_note_as_cash_pay.handlers.buttons import (
    MarkAsCashPayButton,
    UnmarkCashPayButton,
)
from mark_note_as_cash_pay.handlers.route_claims import RouteLabeledClaims
from mark_note_as_cash_pay.helpers.cash_pay import CODING_QUEUE
from tests.conftest import ENABLED, make_claim, methods

BUTTONS = "mark_note_as_cash_pay.handlers.buttons"
ROUTE = "mark_note_as_cash_pay.handlers.route_claims"


def _button(cls, secrets, event_name="SHOW_NOTE_HEADER_DROPDOWN_BUTTON", key=None):
    event = MagicMock()
    event.name = event_name
    event.context = {"note_id": "101", "user": {"id": "staff-1"}}
    if key:
        event.context["key"] = key
    handler = cls(event=event, secrets=secrets)
    return handler


@pytest.fixture
def note_and_claim():
    """Patch note + claim lookups in the buttons module; yield a setter."""
    state = {
        "note": SimpleNamespace(note_type_version=SimpleNamespace(is_billable=True)),
        "claim": None,
    }
    with (
        patch(f"{BUTTONS}.note_from_context", side_effect=lambda _c: state["note"]),
        patch(f"{BUTTONS}.claim_for_note", side_effect=lambda _n: state["claim"]),
        patch(f"{BUTTONS}.actor_name", return_value="Sam Lee"),
    ):
        yield state


def _shows(handler) -> bool:
    effects = handler.compute()
    return bool(effects) and effects[0].type == EffectType.SHOW_ACTION_BUTTON


class TestVisibility:
    def test_hidden_when_plugin_off(self, note_and_claim) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        assert not _shows(_button(MarkAsCashPayButton, {}))
        assert not _shows(_button(UnmarkCashPayButton, {}))

    def test_mark_shown_for_unlabeled_claim_unmark_hidden(self, note_and_claim) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        assert _shows(_button(MarkAsCashPayButton, ENABLED))
        assert not _shows(_button(UnmarkCashPayButton, ENABLED))

    def test_unmark_shown_for_labeled_claim_mark_hidden(self, note_and_claim) -> None:
        note_and_claim["claim"] = make_claim("CashPay", labeled=True)
        assert not _shows(_button(MarkAsCashPayButton, ENABLED))
        assert _shows(_button(UnmarkCashPayButton, ENABLED))

    def test_hidden_on_non_billable_note(self, note_and_claim) -> None:
        note_and_claim["note"] = SimpleNamespace(
            note_type_version=SimpleNamespace(is_billable=False)
        )
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        assert not _shows(_button(MarkAsCashPayButton, ENABLED))

    def test_hidden_when_note_has_no_claim(self, note_and_claim) -> None:
        assert not _shows(_button(MarkAsCashPayButton, ENABLED))

    def test_visibility_never_checks_the_queue(self, note_and_claim) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        with patch(f"{BUTTONS}.config_problem") as cp:
            _button(MarkAsCashPayButton, ENABLED).compute()
            cp.assert_not_called()


class TestClick:
    def _click(self, cls, secrets):
        return _button(
            cls, secrets, event_name="ACTION_BUTTON_CLICKED", key=cls.BUTTON_KEY
        ).compute()

    def test_click_while_off_does_nothing(self, note_and_claim, claim_effect) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        assert self._click(MarkAsCashPayButton, {}) == []
        assert claim_effect.calls == []

    def test_missing_queue_shows_modal_and_changes_nothing(
        self, note_and_claim, claim_effect, queue_exists
    ) -> None:
        queue_exists.objects.filter.return_value.exists.return_value = False
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        effects = self._click(MarkAsCashPayButton, ENABLED)
        assert len(effects) == 1 and effects[0].type == EffectType.LAUNCH_MODAL
        assert "does not exist" in effects[0].payload
        assert claim_effect.calls == []

    def test_unset_queue_setting_shows_modal(
        self, note_and_claim, claim_effect, queue_exists
    ) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        secrets = {**ENABLED, "CASH_PAY_QUEUE_NAME": ""}
        effects = self._click(MarkAsCashPayButton, secrets)
        assert effects[0].type == EffectType.LAUNCH_MODAL
        assert "CASH_PAY_QUEUE_NAME is not set" in effects[0].payload

    def test_no_claim_shows_modal(
        self, note_and_claim, claim_effect, queue_exists
    ) -> None:
        effects = self._click(MarkAsCashPayButton, ENABLED)
        assert effects[0].type == EffectType.LAUNCH_MODAL
        assert claim_effect.calls == []

    def test_mark_click_labels_and_moves(
        self, note_and_claim, claim_effect, queue_exists
    ) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        effects = self._click(MarkAsCashPayButton, ENABLED)
        assert methods(effects) == ["add_labels", "move_to_queue", "add_comment"]
        assert "Sam Lee" in effects[2][1]

    def test_unmark_click_returns_to_coding(
        self, note_and_claim, claim_effect, queue_exists
    ) -> None:
        note_and_claim["claim"] = make_claim("CashPay", labeled=True)
        effects = self._click(UnmarkCashPayButton, ENABLED)
        assert methods(effects) == ["remove_labels", "move_to_queue", "add_comment"]
        assert effects[1][1] == CODING_QUEUE

    def test_custom_names_flow_through(
        self, note_and_claim, claim_effect, queue_exists
    ) -> None:
        note_and_claim["claim"] = make_claim(CODING_QUEUE, labeled=False)
        secrets = {
            **ENABLED,
            "CASH_PAY_QUEUE_NAME": "SelfPay",
            "CASH_PAY_LABEL_NAME": "Self Pay",
        }
        effects = self._click(MarkAsCashPayButton, secrets)
        assert effects[0][1] == ["Self Pay"]
        assert effects[1][1] == "SelfPay"
        queue_exists.objects.filter.assert_called_with(name="SelfPay")


class TestRoute:
    def _run(self, secrets, claim):
        event = MagicMock()
        event.target.id = "claim-1"
        handler = RouteLabeledClaims(event=event, secrets=secrets)
        with patch(f"{ROUTE}.Claim") as model:
            model.objects.select_related.return_value.filter.return_value.first.return_value = claim
            effects = handler.compute()
            return effects, model

    def test_off_does_no_query(self, claim_effect) -> None:
        effects, model = self._run({}, make_claim(CODING_QUEUE, labeled=True))
        assert effects == []
        model.objects.select_related.assert_not_called()

    def test_only_claims_now_in_coding_are_read(
        self, claim_effect, queue_exists
    ) -> None:
        _, model = self._run(ENABLED, None)
        model.objects.select_related.return_value.filter.assert_called_once_with(
            id="claim-1", current_queue__name=CODING_QUEUE
        )

    def test_unlabeled_claim_is_left_alone(self, claim_effect, queue_exists) -> None:
        effects, _ = self._run(ENABLED, make_claim(CODING_QUEUE, labeled=False))
        assert effects == []
        queue_exists.objects.filter.assert_not_called()

    def test_labeled_claim_in_coding_is_routed(
        self, claim_effect, queue_exists
    ) -> None:
        effects, _ = self._run(ENABLED, make_claim(CODING_QUEUE, labeled=True))
        assert methods(effects) == ["move_to_queue", "add_comment"]
        assert effects[0][1] == "CashPay"

    def test_missing_queue_leaves_claim_in_coding(
        self, claim_effect, queue_exists
    ) -> None:
        queue_exists.objects.filter.return_value.exists.return_value = False
        effects, _ = self._run(ENABLED, make_claim(CODING_QUEUE, labeled=True))
        assert effects == []
        assert claim_effect.calls == []
