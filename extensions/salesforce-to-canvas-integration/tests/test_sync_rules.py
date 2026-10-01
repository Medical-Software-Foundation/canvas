"""Tests for the auto apply filter evaluator.

Covers every hard gate, both configurable layers, every validity branch, the
layering and short circuit order, reason naming, and the dataclass defaults.
The evaluator is pure, so a fixed ``TODAY`` makes the future birthdate check
deterministic.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from salesforce_to_canvas_integration.services.field_mapping import MappedPatient
from salesforce_to_canvas_integration.services.sync_rules import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_MODIFY,
    DEFAULT_DELETE_ACTION,
    DEFAULT_REQUIRED_FIELDS,
    DELETE_ACTION_MARK_INACTIVE,
    REASON_AUTO_CREATE_OFF,
    REASON_AUTO_DELETE_OFF,
    REASON_AUTO_MODIFY_OFF,
    REASON_DUPLICATE_MATCH,
    REASON_INCOMPLETE_ADDRESS,
    REASON_LINK_PENDING,
    REASON_MAPPING_FAILED,
    REASON_PREVIOUSLY_SKIPPED,
    SyncDecision,
    SyncFacts,
    SyncSettings,
    evaluate,
)

TODAY = date(2026, 1, 1)


def _mapped(**canvas_fields: Any) -> MappedPatient:
    return MappedPatient(canvas_fields=dict(canvas_fields), metadata={}, telecom={})


# A minimal payload that passes every default layer two rule.
def _valid_create() -> MappedPatient:
    return _mapped(
        first_name="Jane",
        last_name="Doe",
        date_of_birth="1985-04-12",
        phone="5551234567",
    )


def _run(
    action: str = ACTION_CREATE,
    *,
    mapped: MappedPatient | None = None,
    settings: SyncSettings | None = None,
    facts: SyncFacts | None = None,
) -> SyncDecision:
    return evaluate(
        action=action,
        mapped=mapped if mapped is not None else _valid_create(),
        settings=settings or SyncSettings(),
        facts=facts or SyncFacts(),
        today=TODAY,
    )


# --------------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------------- #


def test_create_auto_applies_on_defaults() -> None:
    decision = _run(ACTION_CREATE)
    assert decision.auto_apply is True
    assert decision.reasons == ()
    assert decision.held is False


def test_modify_auto_applies_on_defaults() -> None:
    decision = _run(ACTION_MODIFY)
    assert decision.auto_apply is True
    assert decision.reasons == ()


def test_delete_holds_by_default_then_auto_applies_when_enabled() -> None:
    held = _run(ACTION_DELETE, mapped=_mapped())
    assert held.auto_apply is False
    assert held.reasons == (REASON_AUTO_DELETE_OFF,)

    enabled = _run(
        ACTION_DELETE,
        mapped=_mapped(),
        settings=SyncSettings(auto_delete=True),
    )
    assert enabled.auto_apply is True
    assert enabled.reasons == ()


# --------------------------------------------------------------------------- #
# Hard gates
# --------------------------------------------------------------------------- #


def test_mapping_failed_holds() -> None:
    decision = _run(facts=SyncFacts(mapping_failed=True))
    assert decision.auto_apply is False
    assert REASON_MAPPING_FAILED in decision.reasons


def test_previously_skipped_holds() -> None:
    decision = _run(facts=SyncFacts(previously_skipped=True))
    assert decision.auto_apply is False
    assert REASON_PREVIOUSLY_SKIPPED in decision.reasons


def test_link_pending_holds_on_create() -> None:
    decision = _run(ACTION_CREATE, facts=SyncFacts(accepted_create_exists=True))
    assert decision.auto_apply is False
    assert decision.reasons == (REASON_LINK_PENDING,)


def test_duplicate_match_holds_on_create() -> None:
    decision = _run(ACTION_CREATE, facts=SyncFacts(duplicate_match=True))
    assert decision.auto_apply is False
    assert decision.reasons == (REASON_DUPLICATE_MATCH,)


def test_link_pending_and_duplicate_do_not_gate_modify() -> None:
    decision = _run(
        ACTION_MODIFY,
        facts=SyncFacts(accepted_create_exists=True, duplicate_match=True),
    )
    assert decision.auto_apply is True


def test_hard_gate_short_circuits_before_layer_two() -> None:
    # A mapping failed row with no usable fields holds on the gate only, never
    # accumulating missing field reasons it cannot evaluate.
    decision = _run(mapped=_mapped(), facts=SyncFacts(mapping_failed=True))
    assert decision.reasons == (REASON_MAPPING_FAILED,)


def test_multiple_create_gates_accumulate() -> None:
    decision = _run(
        ACTION_CREATE,
        facts=SyncFacts(accepted_create_exists=True, duplicate_match=True),
    )
    assert decision.reasons == (REASON_LINK_PENDING, REASON_DUPLICATE_MATCH)


# --------------------------------------------------------------------------- #
# Layer one, per event toggles
# --------------------------------------------------------------------------- #


def test_auto_create_off_holds_create() -> None:
    decision = _run(ACTION_CREATE, settings=SyncSettings(auto_create=False))
    assert decision.auto_apply is False
    assert decision.reasons == (REASON_AUTO_CREATE_OFF,)


def test_auto_modify_off_holds_modify() -> None:
    decision = _run(ACTION_MODIFY, settings=SyncSettings(auto_modify=False))
    assert decision.reasons == (REASON_AUTO_MODIFY_OFF,)


def test_auto_create_off_does_not_gate_modify() -> None:
    decision = _run(ACTION_MODIFY, settings=SyncSettings(auto_create=False))
    assert decision.auto_apply is True


def test_layer_one_short_circuits_before_layer_two() -> None:
    # Auto create off plus a missing field reports only the toggle reason.
    decision = _run(
        ACTION_CREATE,
        mapped=_mapped(first_name="Jane"),
        settings=SyncSettings(auto_create=False),
    )
    assert decision.reasons == (REASON_AUTO_CREATE_OFF,)


# --------------------------------------------------------------------------- #
# Layer two, required field set
# --------------------------------------------------------------------------- #


def test_missing_last_name_holds() -> None:
    decision = _run(mapped=_mapped(first_name="Jane", date_of_birth="1985-04-12"))
    assert decision.auto_apply is False
    assert "missing required last name" in decision.reasons


def test_missing_date_of_birth_holds() -> None:
    decision = _run(mapped=_mapped(first_name="Jane", last_name="Doe"))
    assert "missing required date of birth" in decision.reasons


def test_blank_string_counts_as_missing() -> None:
    decision = _run(
        mapped=_mapped(first_name="Jane", last_name="   ", date_of_birth="1985-04-12")
    )
    assert "missing required last name" in decision.reasons


def test_last_name_floored_for_create_even_when_settings_omit_it() -> None:
    # The create only floor. A required set that omits last name still holds a
    # create that is missing last name, because the writer rejects a create
    # without one. See journal cnv-941/036.
    decision = _run(
        ACTION_CREATE,
        mapped=_mapped(first_name="Jane", date_of_birth="1985-04-12"),
        settings=SyncSettings(required_fields=("first_name", "date_of_birth")),
    )
    assert decision.held is True
    assert "missing required last name" in decision.reasons


def test_last_name_not_floored_for_modify() -> None:
    # Modify carries no floor, it is a delta on a linked patient that already
    # has a last name, so a missing last name does not hold it.
    decision = _run(
        ACTION_MODIFY,
        mapped=_mapped(first_name="Jane", date_of_birth="1985-04-12"),
        settings=SyncSettings(required_fields=("first_name", "date_of_birth")),
    )
    assert decision.auto_apply is True
    assert "missing required last name" not in decision.reasons


def test_configurable_required_field_holds_when_absent() -> None:
    decision = _run(
        settings=SyncSettings(
            required_fields=("first_name", "last_name", "date_of_birth", "email")
        )
    )
    assert "missing required email" in decision.reasons


def test_missing_required_fields_accumulate_in_order() -> None:
    decision = _run(mapped=_mapped())
    assert decision.reasons == (
        "missing required first name",
        "missing required last name",
        "missing required date of birth",
        "missing required phone",
    )


# --------------------------------------------------------------------------- #
# Layer two, address group integrity
# --------------------------------------------------------------------------- #


def test_partial_address_holds() -> None:
    mapped = _mapped(
        first_name="Jane",
        last_name="Doe",
        date_of_birth="1985-04-12",
        address_line_1="1 Main St",
        city="Austin",
        # state and postal_code missing
    )
    decision = _run(mapped=mapped)
    assert REASON_INCOMPLETE_ADDRESS in decision.reasons


def test_complete_address_passes() -> None:
    mapped = _mapped(
        first_name="Jane",
        last_name="Doe",
        date_of_birth="1985-04-12",
        phone="5551234567",
        address_line_1="1 Main St",
        city="Austin",
        state="TX",
        postal_code="78701",
    )
    decision = _run(mapped=mapped)
    assert decision.auto_apply is True


def test_no_address_passes() -> None:
    decision = _run(mapped=_valid_create())
    assert decision.auto_apply is True


def test_address_group_off_allows_partial() -> None:
    mapped = _mapped(
        first_name="Jane",
        last_name="Doe",
        date_of_birth="1985-04-12",
        phone="5551234567",
        address_line_1="1 Main St",
    )
    decision = _run(mapped=mapped, settings=SyncSettings(address_group_integrity=False))
    assert decision.auto_apply is True


# --------------------------------------------------------------------------- #
# Layer two, validity checks
# --------------------------------------------------------------------------- #


def _valid_with(**extra: Any) -> MappedPatient:
    base: dict[str, Any] = {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "1985-04-12",
        "phone": "5551234567",
    }
    base.update(extra)
    return MappedPatient(canvas_fields=base, metadata={}, telecom={})


def test_unparseable_birthdate_holds() -> None:
    decision = _run(mapped=_valid_with(date_of_birth="not-a-date"))
    assert "invalid date of birth" in decision.reasons


def test_future_birthdate_holds() -> None:
    decision = _run(mapped=_valid_with(date_of_birth="2099-01-01"))
    assert "invalid date of birth" in decision.reasons


def test_birthdate_equal_to_today_passes() -> None:
    decision = _run(mapped=_valid_with(date_of_birth=TODAY.isoformat()))
    assert decision.auto_apply is True


def test_invalid_sex_holds_valid_passes() -> None:
    bad = _run(mapped=_valid_with(sex_at_birth="banana"))
    assert "invalid sex at birth" in bad.reasons
    good = _run(mapped=_valid_with(sex_at_birth="female"))
    assert good.auto_apply is True


def test_invalid_email_holds_valid_passes() -> None:
    bad = _run(mapped=_valid_with(email="not-an-email"))
    assert "invalid email" in bad.reasons
    good = _run(mapped=_valid_with(email="jane@example.com"))
    assert good.auto_apply is True


def test_invalid_phone_holds_valid_passes() -> None:
    bad = _run(mapped=_valid_with(phone="12345"))
    assert "invalid phone" in bad.reasons
    good = _run(mapped=_valid_with(phone="+1 (555) 123-4567"))
    assert good.auto_apply is True


def test_invalid_state_holds_when_us() -> None:
    decision = _run(
        mapped=_valid_with(
            address_line_1="1 Main St",
            city="Austin",
            state="Texas",
            postal_code="78701",
        )
    )
    assert "invalid state" in decision.reasons


def test_invalid_postal_holds_when_us() -> None:
    decision = _run(
        mapped=_valid_with(
            address_line_1="1 Main St",
            city="Austin",
            state="TX",
            postal_code="78A01",
        )
    )
    assert "invalid postal code" in decision.reasons


def test_nine_digit_postal_passes() -> None:
    decision = _run(
        mapped=_valid_with(
            address_line_1="1 Main St",
            city="Austin",
            state="TX",
            postal_code="78701-1234",
        )
    )
    assert decision.auto_apply is True


def test_non_us_country_skips_state_and_postal_format() -> None:
    decision = _run(
        mapped=_valid_with(
            address_line_1="1 King St",
            city="Toronto",
            state="Ontario",
            postal_code="M5H 2N2",
            country="Canada",
        )
    )
    assert decision.auto_apply is True


def test_validity_off_allows_invalid_values() -> None:
    decision = _run(
        mapped=_valid_with(date_of_birth="2099-01-01", email="nope"),
        settings=SyncSettings(validity_checks=False),
    )
    assert decision.auto_apply is True


def test_layer_two_failures_accumulate() -> None:
    decision = _run(
        mapped=_mapped(
            first_name="Jane",
            date_of_birth="2099-01-01",
            email="bad",
        )
    )
    assert "missing required last name" in decision.reasons
    assert "invalid date of birth" in decision.reasons
    assert "invalid email" in decision.reasons


# --------------------------------------------------------------------------- #
# Delete never touches layer two
# --------------------------------------------------------------------------- #


def test_delete_ignores_layer_two_rules() -> None:
    # An empty payload that would fail every layer two rule still auto applies
    # as a delete, because delete writes no demographics.
    decision = _run(
        ACTION_DELETE,
        mapped=_mapped(),
        settings=SyncSettings(auto_delete=True),
    )
    assert decision.auto_apply is True


# --------------------------------------------------------------------------- #
# Dataclass shape and defaults
# --------------------------------------------------------------------------- #


def test_settings_defaults() -> None:
    settings = SyncSettings()
    assert settings.auto_create is True
    assert settings.auto_modify is True
    assert settings.auto_delete is False
    assert settings.delete_action == DEFAULT_DELETE_ACTION == DELETE_ACTION_MARK_INACTIVE
    assert settings.required_fields == DEFAULT_REQUIRED_FIELDS
    assert settings.address_group_integrity is True
    assert settings.validity_checks is True


def test_facts_defaults_are_all_false() -> None:
    facts = SyncFacts()
    assert facts.linked is False
    assert facts.accepted_create_exists is False
    assert facts.previously_skipped is False
    assert facts.duplicate_match is False
    assert facts.mapping_failed is False


def test_decision_held_property() -> None:
    assert SyncDecision(True).held is False
    assert SyncDecision(False, ("x",)).held is True
