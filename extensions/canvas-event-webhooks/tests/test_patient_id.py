"""patient_id extraction and envelope tests."""

from __future__ import annotations

import json
from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.config_store import WebhookConfig
from canvas_event_webhooks.events_catalog import is_patient_related
from canvas_event_webhooks.handlers.base import extract_patient_id
from canvas_event_webhooks.handlers.event_handlers import (
    AppointmentWebhookHandler,
    BillingWebhookHandler,
    DocumentWebhookHandler,
    LabWebhookHandler,
    MedicationWebhookHandler,
    MessageWebhookHandler,
    NoteWebhookHandler,
    PatientWebhookHandler,
    PrescriptionWebhookHandler,
    StaffWebhookHandler,
    TaskWebhookHandler,
)


def _event(event_type: int, context: dict | None = None, target_id: str = "rec-1") -> Mock:
    event = Mock()
    event.type = event_type
    event.target = Mock()
    event.target.id = target_id
    event.target.type = None
    event.context = context or {}
    return event


def _wh() -> WebhookConfig:
    return WebhookConfig(
        id="1",
        name="t",
        url="https://example.com/h",
        secret="s",
        events=[
            "PATIENT_CREATED",
            "APPOINTMENT_CREATED",
            "TASK_CREATED",
            "NOTE_CREATED",
            "MEDICATION_LIST_ITEM_CREATED",
            "PRESCRIPTION_CREATED",
            "MESSAGE_CREATED",
            "LAB_ORDER_CREATED",
            "DOCUMENT_RECEIVED",
            "CLAIM_CREATED",
            "STAFF_CREATED",
        ],
    )


def _payload(handler_cls, event_type, context):
    handler = handler_cls(event=_event(event_type, context=context), secrets={})
    effects = handler._dispatch(webhooks=[_wh()])
    effect = next(e for e in effects if e.type == EffectType.HTTP_REQUEST)
    return json.loads(json.loads(effect.payload)["data"]["body"])


def test_extract_patient_id_from_nested_patient_object():
    event = _event(EventType.PATIENT_CREATED, {"patient": {"id": "pt-123"}})
    assert extract_patient_id(event) == "pt-123"


def test_extract_patient_id_from_top_level_key():
    event = _event(EventType.NOTE_STATE_CHANGE_EVENT_CREATED, {"patient_id": "pt-456"})
    assert extract_patient_id(event) == "pt-456"


def test_extract_patient_id_from_related_record():
    event = _event(
        EventType.PRESCRIPTION_CREATED,
        {"prescription": {"patient_id": "pt-789"}},
    )
    assert extract_patient_id(event) == "pt-789"


def test_extract_patient_id_returns_none_when_absent():
    event = _event(EventType.STAFF_CREATED, {"staff": {"id": "st-1"}})
    assert extract_patient_id(event) is None


def test_patient_related_events_include_top_level_patient_id():
    cases = [
        (PatientWebhookHandler, EventType.PATIENT_CREATED, {"patient": {"id": "p1"}}),
        (AppointmentWebhookHandler, EventType.APPOINTMENT_CREATED, {"patient": {"id": "p2"}}),
        (TaskWebhookHandler, EventType.TASK_CREATED, {"patient_id": "p3"}),
        (NoteWebhookHandler, EventType.NOTE_CREATED, {"note": {"patient": {"id": "p4"}}}),
        (MedicationWebhookHandler, EventType.MEDICATION_LIST_ITEM_CREATED, {"patient": {"id": "p5"}}),
        (PrescriptionWebhookHandler, EventType.PRESCRIPTION_CREATED, {"patient": {"id": "p6"}}),
        (MessageWebhookHandler, EventType.MESSAGE_CREATED, {"patient": {"id": "p7"}}),
        (LabWebhookHandler, EventType.LAB_ORDER_CREATED, {"patient": {"id": "p8"}}),
        (DocumentWebhookHandler, EventType.DOCUMENT_RECEIVED, {"patient": {"id": "p9"}}),
        (BillingWebhookHandler, EventType.CLAIM_CREATED, {"patient": {"id": "p10"}}),
    ]
    for handler_cls, event_type, context in cases:
        body = _payload(handler_cls, event_type, context)
        assert "patient_id" in body, EventType.Name(event_type)
        assert body["patient_id"]
        assert is_patient_related(body["event"])


def test_staff_event_does_not_fabricate_patient_id():
    body = _payload(StaffWebhookHandler, EventType.STAFF_CREATED, {"staff": {"id": "st-9"}})
    assert "patient_id" not in body
    assert not is_patient_related("STAFF_CREATED")
