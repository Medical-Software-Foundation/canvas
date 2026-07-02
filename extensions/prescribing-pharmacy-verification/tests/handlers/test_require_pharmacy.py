from unittest.mock import MagicMock

import pytest

from prescribing_pharmacy_verification.handlers.require_pharmacy import (
    RequirePharmacyOnPrescription,
)


def _build_handler(fields: dict | None) -> RequirePharmacyOnPrescription:
    """Construct the handler with a mock event whose context exposes `fields`."""
    handler = RequirePharmacyOnPrescription.__new__(RequirePharmacyOnPrescription)
    event = MagicMock()
    event.context = {"fields": fields} if fields is not None else {}
    handler.event = event
    return handler


def test_responds_to_all_three_post_validation_events() -> None:
    from canvas_sdk.events import EventType

    assert RequirePharmacyOnPrescription.RESPONDS_TO == [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION),
    ]


def test_blocks_when_pharmacy_missing() -> None:
    handler = _build_handler({"sig": "Take one tablet daily"})

    effects = handler.compute()

    assert len(effects) == 1
    payload = str(effects[0].payload)
    assert RequirePharmacyOnPrescription.ERROR_MESSAGE in payload


def test_blocks_when_pharmacy_is_none() -> None:
    handler = _build_handler({"pharmacy": None})

    effects = handler.compute()

    assert len(effects) == 1
    payload = str(effects[0].payload)
    assert RequirePharmacyOnPrescription.ERROR_MESSAGE in payload


def test_blocks_when_pharmacy_is_empty_dict() -> None:
    handler = _build_handler({"pharmacy": {}})

    effects = handler.compute()

    assert len(effects) == 1


def test_blocks_when_pharmacy_dict_has_blank_id() -> None:
    handler = _build_handler({"pharmacy": {"ncpdp_id": "   "}})

    effects = handler.compute()

    assert len(effects) == 1


def test_blocks_when_context_has_no_fields_key() -> None:
    handler = _build_handler(None)

    effects = handler.compute()

    assert len(effects) == 1


@pytest.mark.parametrize(
    "pharmacy_value",
    [
        {"ncpdp_id": "1234567"},
        {"id": "abc-123"},
        {"value": "999"},
        {"ncpdp_id": "1234567", "name": "Acme Pharmacy"},
        "1234567",
    ],
)
def test_allows_when_pharmacy_set(pharmacy_value: object) -> None:
    handler = _build_handler({"pharmacy": pharmacy_value})

    effects = handler.compute()

    assert effects == []


@pytest.mark.parametrize("pharmacy_value", [["1234567"], 1234567, object()])
def test_blocks_when_pharmacy_is_unexpected_type(pharmacy_value: object) -> None:
    handler = _build_handler({"pharmacy": pharmacy_value})

    effects = handler.compute()

    assert len(effects) == 1
