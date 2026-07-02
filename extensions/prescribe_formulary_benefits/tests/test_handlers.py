"""Behavior tests for the three workflow handlers.

These exercise the real SDK Surescripts effects/events, so they are skipped on
environments where that (currently unreleased) SDK functionality isn't
installed, and run fully on the instance/CI that has it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("canvas_sdk.effects.surescripts.surescripts_messages")
pytest.importorskip("canvas_sdk.events.surescripts")

from canvas_sdk.effects import EffectType  # noqa: E402
from canvas_sdk.events import EventType  # noqa: E402

from prescribe_formulary_benefits.protocols.benefits_workflow import (  # noqa: E402
    BenefitsResponseHandler,
    EligibilityResponseHandler,
    PrescribeBenefitsTrigger,
)
from prescribe_formulary_benefits.workflow import (  # noqa: E402
    fingerprint_key,
    store_context,
)

_MODULE = "prescribe_formulary_benefits.protocols.benefits_workflow"

_ELIGIBILITY_CONTEXT = {
    "stage": "eligibility",
    "command_uuid": "cmd-1",
    "command_kind": "prescribe",
    "patient_id": "pat-1",
    "staff_id": "stf-1",
    "ndc": "00006010654",
    "description": "Lisinopril 10 mg tablet",
}


def _stored_stages(fake_cache) -> list[str]:
    stages = []
    for value in fake_cache.store.values():
        try:
            stages.append(json.loads(value).get("stage"))
        except (TypeError, ValueError):
            continue
    return stages


# --- PrescribeBenefitsTrigger ---------------------------------------------


def _trigger_event(event_type=EventType.PRESCRIBE_COMMAND__POST_UPDATE) -> Mock:
    event = Mock()
    event.type = event_type
    event.target.id = "cmd-1"
    event.context = {
        "fields": {
            "prescribe": {"text": "Lisinopril 10 mg tablet", "value": 606783},
            "type_to_dispense": {"extra": {"representative_ndc": "00006010654"}},
        },
        "note": {"uuid": "note-1"},
    }
    return event


def test_trigger_responds_to_originate_and_update_for_all_commands() -> None:
    for event in (
        EventType.PRESCRIBE_COMMAND__POST_ORIGINATE,
        EventType.PRESCRIBE_COMMAND__POST_UPDATE,
        EventType.REFILL_COMMAND__POST_ORIGINATE,
        EventType.REFILL_COMMAND__POST_UPDATE,
        EventType.ADJUST_PRESCRIPTION_COMMAND__POST_ORIGINATE,
        EventType.ADJUST_PRESCRIPTION_COMMAND__POST_UPDATE,
    ):
        assert EventType.Name(event) in PrescribeBenefitsTrigger.RESPONDS_TO


@patch(f"{_MODULE}.get_cache")
@patch(f"{_MODULE}.Command")
def test_trigger_fires_on_originate_with_preselected_medication(
    mock_command, mock_get_cache, fake_cache
) -> None:
    """A command that originates with the medication already set still starts the workflow."""
    command = Mock()
    command.patient.id = "pat-1"
    command.note.provider.id = "stf-1"
    mock_command.objects.select_related.return_value.get.return_value = command
    mock_get_cache.return_value = fake_cache

    event = _trigger_event(EventType.REFILL_COMMAND__POST_ORIGINATE)
    effects = PrescribeBenefitsTrigger(event=event).compute()

    assert [e.type for e in effects] == [
        EffectType.SET_COMMAND_CUSTOM_HTML,
        EffectType.SEND_SURESCRIPTS_ELIGIBILITY_REQUEST,
    ]


@patch(f"{_MODULE}.get_cache")
@patch(f"{_MODULE}.Command")
def test_trigger_fires_eligibility_and_loading_html(mock_command, mock_get_cache, fake_cache) -> None:
    command = Mock()
    command.patient.id = "pat-1"
    command.note.provider.id = "stf-1"
    mock_command.objects.select_related.return_value.get.return_value = command
    mock_get_cache.return_value = fake_cache

    effects = PrescribeBenefitsTrigger(event=_trigger_event()).compute()

    assert [e.type for e in effects] == [
        EffectType.SET_COMMAND_CUSTOM_HTML,
        EffectType.SEND_SURESCRIPTS_ELIGIBILITY_REQUEST,
    ]
    # Fingerprint recorded so repeat POST_UPDATEs don't re-fire.
    assert fake_cache.get(fingerprint_key("cmd-1")) == "00006010654"
    # Eligibility context stashed for the response handler.
    assert "eligibility" in _stored_stages(fake_cache)


@patch(f"{_MODULE}.get_cache")
@patch(f"{_MODULE}.Command")
def test_trigger_dedupes_same_medication(mock_command, mock_get_cache, fake_cache) -> None:
    fake_cache.set(fingerprint_key("cmd-1"), "00006010654")
    mock_get_cache.return_value = fake_cache

    effects = PrescribeBenefitsTrigger(event=_trigger_event()).compute()

    assert effects == []
    mock_command.objects.select_related.assert_not_called()


@patch(f"{_MODULE}.get_cache")
@patch(f"{_MODULE}.Command")
def test_trigger_noop_without_medication(mock_command, mock_get_cache, fake_cache) -> None:
    mock_get_cache.return_value = fake_cache
    event = _trigger_event()
    event.context = {"fields": {"sig": "take one daily"}, "note": {"uuid": "note-1"}}

    assert PrescribeBenefitsTrigger(event=event).compute() == []


# --- EligibilityResponseHandler -------------------------------------------


def _eligibility_event(correlation_id: str, *, error=None, plans=None) -> Mock:
    event = Mock()
    event.type = EventType.SURESCRIPTS_ELIGIBILITY_RESPONSE
    event.context = {
        "correlation_id": correlation_id,
        "patient_id": "pat-1",
        "plans": plans if plans is not None else [{"pbm_name": "Acme", "description": "Acme Commercial"}],
        "error": error,
    }
    return event


@patch(f"{_MODULE}.get_cache")
def test_eligibility_response_fires_benefits_request(mock_get_cache, fake_cache) -> None:
    store_context(fake_cache, "corr-elig", dict(_ELIGIBILITY_CONTEXT))
    mock_get_cache.return_value = fake_cache

    effects = EligibilityResponseHandler(event=_eligibility_event("corr-elig")).compute()

    assert [e.type for e in effects] == [EffectType.SEND_SURESCRIPTS_BENEFITS_REQUEST]
    # The `plan` field MUST be the pbm_name (server matches on it), not the description.
    assert json.loads(effects[0].payload)["data"]["plan"] == "Acme"
    # A benefits-stage context is now stashed for the benefits response.
    assert "benefits" in _stored_stages(fake_cache)


@patch(f"{_MODULE}.get_cache")
def test_eligibility_response_ignores_unknown_correlation(mock_get_cache, fake_cache) -> None:
    mock_get_cache.return_value = fake_cache
    assert EligibilityResponseHandler(event=_eligibility_event("not-mine")).compute() == []


@patch(f"{_MODULE}.get_cache")
def test_eligibility_error_renders_error_html(mock_get_cache, fake_cache) -> None:
    store_context(fake_cache, "corr-elig", dict(_ELIGIBILITY_CONTEXT))
    mock_get_cache.return_value = fake_cache

    effects = EligibilityResponseHandler(
        event=_eligibility_event("corr-elig", error="Pharmacy upstream error")
    ).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.SET_COMMAND_CUSTOM_HTML
    custom_html = json.loads(effects[0].payload)["data"]["custom_html"]
    assert "Pharmacy upstream error" in custom_html


# --- BenefitsResponseHandler ----------------------------------------------


def _benefits_event(correlation_id: str) -> Mock:
    event = Mock()
    event.type = EventType.SURESCRIPTS_BENEFITS_RESPONSE
    event.context = {
        "correlation_id": correlation_id,
        "patient_id": "pat-1",
        "medication_ndc": "00006010654",
        "coverages": [
            {
                "pbm_name": "Acme PBM",
                "payer_id": "P1",
                "formulary_status": "On Formulary - Tier 2",
                "prior_authorization_required": True,
                "step_therapy_required": False,
                "quantity_limits": ["30 / 30 days"],
                "copays": ["$10"],
                "alternatives": [{"ndc": "00093-7146-01", "description": "Generic 5 mg"}],
                "rejected": False,
                "reject_reason": None,
            }
        ],
        "error": None,
    }
    return event


@patch(f"{_MODULE}.get_cache")
def test_benefits_response_writes_custom_html(mock_get_cache, fake_cache) -> None:
    store_context(
        fake_cache, "corr-ben", {**_ELIGIBILITY_CONTEXT, "stage": "benefits"}
    )
    mock_get_cache.return_value = fake_cache

    effects = BenefitsResponseHandler(event=_benefits_event("corr-ben")).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.SET_COMMAND_CUSTOM_HTML
    custom_html = json.loads(effects[0].payload)["data"]["custom_html"]
    assert "On Formulary - Tier 2" in custom_html
    assert "Generic 5 mg" in custom_html
    assert "Lisinopril 10 mg tablet" in custom_html


@patch(f"{_MODULE}.get_cache")
def test_benefits_response_ignores_unknown_correlation(mock_get_cache, fake_cache) -> None:
    mock_get_cache.return_value = fake_cache
    assert BenefitsResponseHandler(event=_benefits_event("not-mine")).compute() == []
