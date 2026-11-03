"""Behavior tests for the cash-pay decision and effect builders."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from canvas_sdk.effects import EffectType

from mark_note_as_cash_pay.helpers import cash_pay
from mark_note_as_cash_pay.helpers.cash_pay import (
    CODING_QUEUE,
    Config,
    actor_name,
    build_mark_effects,
    build_route_effects,
    build_unmark_effects,
    config_problem,
    error_modal,
    get_config,
    note_from_context,
    note_is_billable,
)
from tests.conftest import ENABLED, HELPERS, make_claim, methods

CFG = Config(enabled=True, queue_name="CashPay", label_name="Cash Pay")


class TestGetConfig:
    def test_off_by_default(self) -> None:
        assert get_config({}).enabled is False

    @pytest.mark.parametrize("value", ["", "false", "yes", "1", "on", None])
    def test_anything_but_true_is_off(self, value) -> None:
        assert get_config({"CASH_PAY_ENABLED": value}).enabled is False

    def test_true_is_case_and_space_insensitive(self) -> None:
        assert get_config({"CASH_PAY_ENABLED": " TRUE "}).enabled is True

    def test_label_defaults_to_cash_pay(self) -> None:
        assert get_config({"CASH_PAY_LABEL_NAME": "  "}).label_name == "Cash Pay"

    def test_names_come_from_settings(self) -> None:
        cfg = get_config({**ENABLED, "CASH_PAY_LABEL_NAME": "Self Pay"})
        assert cfg == Config(enabled=True, queue_name="CashPay", label_name="Self Pay")

    def test_non_mapping_secrets_fail_closed(self) -> None:
        assert get_config(None).enabled is False


class TestConfigProblem:
    def test_missing_queue_setting(self, queue_exists) -> None:
        problem = config_problem(
            Config(enabled=True, queue_name="", label_name="Cash Pay")
        )
        assert problem == "CASH_PAY_QUEUE_NAME is not set."
        queue_exists.objects.filter.assert_not_called()

    def test_queue_not_found_is_reported_and_never_created(self, queue_exists) -> None:
        queue_exists.objects.filter.return_value.exists.return_value = False
        problem = config_problem(CFG)
        assert problem is not None and "'CashPay' does not exist" in problem
        queue_exists.objects.filter.assert_called_once_with(name="CashPay")
        queue_exists.objects.create.assert_not_called()
        queue_exists.objects.get_or_create.assert_not_called()

    def test_existing_queue_is_fine(self, queue_exists) -> None:
        assert config_problem(CFG) is None


class TestErrorModal:
    def test_is_a_modal_and_escapes_the_message(self) -> None:
        effect = error_modal("queue '<b>x</b>' missing")
        assert effect.type == EffectType.LAUNCH_MODAL
        assert "&lt;b&gt;x&lt;/b&gt;" in effect.payload
        assert "<b>x</b>" not in effect.payload


class TestNoteLookup:
    def test_numeric_id_is_treated_as_dbid(self) -> None:
        with patch(f"{HELPERS}.Note") as note:
            qs = note.objects.select_related.return_value
            note_from_context({"note_id": "222755"})
            qs.filter.assert_called_once_with(dbid=222755)

    def test_uuid_id_is_looked_up_by_id(self) -> None:
        uid = "0b8f8b8e-0000-4000-8000-000000000001"
        with patch(f"{HELPERS}.Note") as note:
            qs = note.objects.select_related.return_value
            note_from_context({"note_id": uid})
            qs.filter.assert_called_once_with(id=uid)

    def test_missing_note_id_returns_none_without_query(self) -> None:
        with patch(f"{HELPERS}.Note") as note:
            assert note_from_context({}) is None
            note.objects.select_related.assert_not_called()

    @pytest.mark.parametrize(
        ("ntv", "expected"),
        [
            (SimpleNamespace(is_billable=True), True),
            (SimpleNamespace(is_billable=False), False),
            (None, False),
        ],
    )
    def test_billable(self, ntv, expected) -> None:
        assert note_is_billable(SimpleNamespace(note_type_version=ntv)) is expected


class TestActorName:
    def test_uses_staff_name(self) -> None:
        with patch(f"{HELPERS}.Staff") as staff:
            staff.objects.filter.return_value.values.return_value.first.return_value = {
                "first_name": "Sam",
                "last_name": "Lee",
            }
            assert actor_name({"user": {"id": "s1"}}) == "Sam Lee"
            staff.objects.filter.assert_called_once_with(id="s1")

    def test_falls_back_when_no_user(self) -> None:
        assert actor_name({}) == "a staff member"


class TestMark:
    def test_in_coding_labels_moves_and_comments(self, claim_effect) -> None:
        effects = build_mark_effects(
            make_claim(CODING_QUEUE, labeled=False), CFG, "Sam Lee"
        )
        assert methods(effects) == ["add_labels", "move_to_queue", "add_comment"]
        assert effects[0][1] == ["Cash Pay"]
        assert effects[1][1] == "CashPay"
        assert (
            "Sam Lee" in effects[2][1]
            and "Moved to the 'CashPay' queue" in effects[2][1]
        )

    def test_already_labeled_does_not_add_label_twice(self, claim_effect) -> None:
        effects = build_mark_effects(make_claim(CODING_QUEUE, labeled=True), CFG, "x")
        assert methods(effects) == ["move_to_queue", "add_comment"]

    @pytest.mark.parametrize("queue", ["Appointment", "NeedsClinicianReview"])
    def test_before_coding_labels_and_waits(self, claim_effect, queue) -> None:
        effects = build_mark_effects(make_claim(queue, labeled=False), CFG, "x")
        assert methods(effects) == ["add_labels", "add_comment"]
        assert "when it reaches NeedsCodingReview" in effects[1][1]

    @pytest.mark.parametrize(
        "queue",
        ["QueuedForSubmission", "FiledAwaitingResponse", "PatientBalance", "Trash"],
    )
    def test_past_coding_labels_only_and_says_so(self, claim_effect, queue) -> None:
        effects = build_mark_effects(make_claim(queue, labeled=False), CFG, "x")
        assert methods(effects) == ["add_labels", "add_comment"]
        assert f"Left in its current queue ('{queue}')" in effects[1][1]

    def test_already_in_cash_queue_does_not_move(self, claim_effect) -> None:
        effects = build_mark_effects(make_claim("CashPay", labeled=False), CFG, "x")
        assert "move_to_queue" not in methods(effects)

    def test_label_lookup_is_case_insensitive(self, claim_effect) -> None:
        claim = make_claim(CODING_QUEUE, labeled=True)
        build_mark_effects(claim, CFG, "x")
        claim.labels.filter.assert_called_with(name__iexact="Cash Pay")


class TestUnmark:
    def test_in_cash_queue_removes_label_and_returns_to_coding(
        self, claim_effect
    ) -> None:
        effects = build_unmark_effects(make_claim("CashPay", labeled=True), CFG, "Sam")
        assert methods(effects) == ["remove_labels", "move_to_queue", "add_comment"]
        assert effects[0][1] == ["Cash Pay"]
        assert effects[1][1] == CODING_QUEUE
        assert "Unmarked as cash pay by Sam" in effects[2][1]

    def test_elsewhere_removes_label_only(self, claim_effect) -> None:
        effects = build_unmark_effects(
            make_claim("FiledAwaitingResponse", labeled=True), CFG, "x"
        )
        assert methods(effects) == ["remove_labels", "add_comment"]


class TestRoute:
    def test_moves_to_configured_queue_with_comment(self, claim_effect) -> None:
        effects = build_route_effects(make_claim(CODING_QUEUE, labeled=True), CFG)
        assert methods(effects) == ["move_to_queue", "add_comment"]
        assert effects[0][1] == "CashPay"


def test_no_payer_ids_or_queue_creation_in_module() -> None:
    """Guard the lean: names come from settings; nothing creates a queue."""
    import inspect

    source = inspect.getsource(cash_pay)
    assert "create(" not in source
    assert "payer_id" not in source
