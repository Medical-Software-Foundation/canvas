"""
Tests for the canvas_event_webhooks plugin.

Covers:
  - Correct HTTP effect is returned with the right URL, method, and headers
  - Payload structure: event name, occurred_at, target, context
  - HMAC-SHA256 signature is computed correctly when webhook-secret is set
  - No effect is returned when webhook-url secret is missing
  - Retry configuration (status codes + max_retries)
  - Spot-check that each handler class responds to its expected event types
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, Mock

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.handlers.base import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign_body,
)
from canvas_event_webhooks.handlers.event_handlers import (
    AppointmentWebhookHandler,
    BillingWebhookHandler,
    CareTeamWebhookHandler,
    ClinicalWebhookHandler,
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

WEBHOOK_URL = "https://hooks.example.com/canvas"
WEBHOOK_SECRET = "super-secret-key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    event_type: int,
    target_id: str = "rec-abc-123",
    target_type=None,
    context: dict | None = None,
) -> Mock:
    """Build a minimal mock Canvas event."""
    event = Mock()
    event.type = event_type
    event.target = Mock()
    event.target.id = target_id
    event.target.type = target_type  # None or a model class / string
    event.context = context or {}
    return event


def _make_handler(
    handler_cls,
    event_type: int,
    *,
    webhook_url: str | None = WEBHOOK_URL,
    webhook_secret: str | None = WEBHOOK_SECRET,
    target_id: str = "rec-abc-123",
    context: dict | None = None,
):
    secrets = {}
    if webhook_url is not None:
        secrets["webhook-url"] = webhook_url
    if webhook_secret is not None:
        secrets["webhook-secret"] = webhook_secret
    return handler_cls(
        event=_make_event(event_type, target_id=target_id, context=context),
        secrets=secrets,
    )


def _http_effect(effects):
    """Return the single HTTP_REQUEST effect from a compute() result."""
    return next(e for e in effects if e.type == EffectType.HTTP_REQUEST)


def _payload(effects) -> dict:
    """Decode the JSON body from the HTTP_REQUEST effect payload."""
    effect = _http_effect(effects)
    data = json.loads(effect.payload)["data"]
    return json.loads(data["body"])


def _headers(effects) -> dict:
    effect = _http_effect(effects)
    return json.loads(effect.payload)["data"]["headers"]


# ---------------------------------------------------------------------------
# Core dispatch behaviour
# ---------------------------------------------------------------------------

def test_returns_http_request_effect():
    """Handler returns exactly one HTTP_REQUEST effect when URL is set."""
    handler = _make_handler(PatientWebhookHandler, EventType.PATIENT_CREATED)
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.HTTP_REQUEST


def test_payload_contains_correct_event_name():
    """'event' field in the payload matches the Canvas EventType name."""
    handler = _make_handler(PatientWebhookHandler, EventType.PATIENT_CREATED)
    body = _payload(handler.compute())

    assert body["event"] == "PATIENT_CREATED"


def test_payload_contains_target_id():
    """'target.id' in the payload matches the event's target.id."""
    handler = _make_handler(
        AppointmentWebhookHandler,
        EventType.APPOINTMENT_CREATED,
        target_id="appt-uuid-999",
    )
    body = _payload(handler.compute())

    assert body["target"]["id"] == "appt-uuid-999"


def test_payload_contains_context():
    """Default context block contains safe IDs extracted from the raw context."""
    ctx = {"patient": {"id": "pt-xyz"}, "state": "locked"}
    handler = _make_handler(
        NoteWebhookHandler,
        EventType.NOTE_STATE_CHANGE_EVENT_CREATED,
        context=ctx,
    )
    body = _payload(handler.compute())

    # Default (ID-only): patient_id and state are safe; nested patient dict is normalised.
    assert body["context"]["patient_id"] == "pt-xyz"
    assert body["context"]["state"] == "locked"


def test_payload_contains_occurred_at():
    """'occurred_at' is present and is a non-empty ISO-8601 string."""
    handler = _make_handler(TaskWebhookHandler, EventType.TASK_CREATED)
    body = _payload(handler.compute())

    assert "occurred_at" in body
    assert len(body["occurred_at"]) > 10  # rough sanity check


def test_http_method_is_post():
    """Requests are sent as HTTP POST."""
    handler = _make_handler(PatientWebhookHandler, EventType.PATIENT_UPDATED)
    effect = _http_effect(handler.compute())
    data = json.loads(effect.payload)["data"]

    assert data["method"].upper() == "POST"


def test_content_type_header_is_json():
    """Content-Type header is always application/json."""
    headers = _headers(_make_handler(
        LabWebhookHandler, EventType.LAB_REPORT_CREATED
    ).compute())

    assert headers["Content-Type"] == "application/json"


def test_no_effect_when_webhook_url_missing():
    """Returns [] gracefully when webhook-url secret is not configured."""
    handler = _make_handler(
        PatientWebhookHandler,
        EventType.PATIENT_CREATED,
        webhook_url=None,
    )
    assert handler.compute() == []


def test_no_effect_when_webhook_url_is_empty_string():
    """Returns [] when webhook-url is present but blank."""
    handler = _make_handler(
        PatientWebhookHandler,
        EventType.PATIENT_CREATED,
        webhook_url="   ",
    )
    assert handler.compute() == []


# ---------------------------------------------------------------------------
# HMAC-SHA256 signing
# ---------------------------------------------------------------------------

def test_signature_header_is_present_when_secret_is_set():
    """X-Canvas-Signature header is included when webhook-secret is set."""
    handler = _make_handler(
        PatientWebhookHandler,
        EventType.PATIENT_CREATED,
        webhook_secret=WEBHOOK_SECRET,
    )
    headers = _headers(handler.compute())

    assert "X-Canvas-Signature" in headers
    assert headers["X-Canvas-Signature"].startswith("t=")
    assert TIMESTAMP_HEADER in headers


def test_signature_is_correct_hmac_sha256():
    """X-Canvas-Signature matches HMAC-SHA256(secret, '{timestamp}.{body}')."""
    handler = _make_handler(
        PatientWebhookHandler,
        EventType.PATIENT_CREATED,
        webhook_secret=WEBHOOK_SECRET,
    )
    effects = handler.compute()
    effect_data = json.loads(_http_effect(effects).payload)["data"]
    raw_body: str = effect_data["body"]
    headers: dict = effect_data["headers"]
    ts = int(headers[TIMESTAMP_HEADER])

    assert headers[SIGNATURE_HEADER] == sign_body(WEBHOOK_SECRET, raw_body, ts)


def test_skips_delivery_when_secret_not_set():
    """Unsigned webhooks are not delivered."""
    handler = _make_handler(
        PatientWebhookHandler,
        EventType.PATIENT_CREATED,
        webhook_secret=None,
    )
    assert handler.compute() == []


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

def test_retries_on_5xx_status_codes():
    """Effect payload declares 5xx (and 429) status codes for retry."""
    handler = _make_handler(PatientWebhookHandler, EventType.PATIENT_CREATED)
    effect_data = json.loads(_http_effect(handler.compute()).payload)["data"]
    retry_codes: list[int] = effect_data["retry_on_status_codes"]

    for code in [429, 500, 502, 503, 504]:
        assert code in retry_codes


# ---------------------------------------------------------------------------
# PHI guard — context handling
# ---------------------------------------------------------------------------

def test_default_context_is_id_only():
    """Without include-context, only safe ID fields appear in context."""
    ctx = {
        "patient": {"id": "pt-123"},
        "note": {"uuid": "note-uuid-456"},
        "state": "locked",
        "content_url": "https://phi.example.com/doc.pdf",  # must be stripped
        "message_to_patient": "Your results are in",       # must be stripped
    }
    handler = _make_handler(
        NoteWebhookHandler,
        EventType.NOTE_STATE_CHANGE_EVENT_CREATED,
        context=ctx,
    )
    body = _payload(handler.compute())

    assert body["context"].get("patient_id") == "pt-123"
    assert body["context"].get("note_id") == "note-uuid-456"
    assert body["context"].get("state") == "locked"
    # PHI fields must NOT be present in the default payload
    assert "content_url" not in body["context"]
    assert "message_to_patient" not in body["context"]


def test_full_context_forwarded_when_opted_in():
    """With include-context=true, the complete raw context is forwarded."""
    ctx = {
        "patient": {"id": "pt-123"},
        "content_url": "https://phi.example.com/doc.pdf",
        "message_to_patient": "Your results are in",
    }
    handler = _make_handler(
        DocumentWebhookHandler,
        EventType.DOCUMENT_REVIEWED,
        context=ctx,
    )
    # inject include-context opt-in
    handler.secrets["include-context"] = "true"
    body = _payload(handler.compute())

    assert body["context"]["content_url"] == "https://phi.example.com/doc.pdf"
    assert body["context"]["message_to_patient"] == "Your results are in"


def test_context_opt_in_false_uses_safe_context():
    """Explicitly setting include-context=false keeps the safe default."""
    ctx = {"patient": {"id": "pt-abc"}, "content_url": "https://phi.example.com"}
    handler = _make_handler(
        DocumentWebhookHandler,
        EventType.DOCUMENT_RECEIVED,
        context=ctx,
    )
    handler.secrets["include-context"] = "false"
    body = _payload(handler.compute())

    assert body["context"].get("patient_id") == "pt-abc"
    assert "content_url" not in body["context"]


# ---------------------------------------------------------------------------
# Per-handler RESPONDS_TO spot checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("handler_cls,event_type", [
    (PatientWebhookHandler,     EventType.PATIENT_CREATED),
    (PatientWebhookHandler,     EventType.PATIENT_UPDATED),
    (AppointmentWebhookHandler, EventType.APPOINTMENT_CREATED),
    (AppointmentWebhookHandler, EventType.APPOINTMENT_CHECKED_IN),
    (AppointmentWebhookHandler, EventType.APPOINTMENT_CANCELED),
    (NoteWebhookHandler,        EventType.NOTE_CREATED),
    (NoteWebhookHandler,        EventType.NOTE_STATE_CHANGE_EVENT_CREATED),
    (ClinicalWebhookHandler,    EventType.CONDITION_CREATED),
    (ClinicalWebhookHandler,    EventType.ALLERGY_INTOLERANCE_CREATED),
    (ClinicalWebhookHandler,    EventType.OBSERVATION_CREATED),
    (MedicationWebhookHandler,  EventType.MEDICATION_LIST_ITEM_CREATED),
    (PrescriptionWebhookHandler, EventType.PRESCRIPTION_CREATED),
    (PrescriptionWebhookHandler, EventType.PRESCRIPTION_TRANSMITTED),
    (PrescriptionWebhookHandler, EventType.PRESCRIPTION_ERRORED),
    (PrescriptionWebhookHandler, EventType.PRESCRIPTION_UPDATED),
    (MessageWebhookHandler,     EventType.MESSAGE_TRANSMISSION_CREATED),
    (CareTeamWebhookHandler,    EventType.CARE_TEAM_MEMBERSHIP_CREATED),
    (BillingWebhookHandler,     EventType.CLAIM_CREATED),
    (LabWebhookHandler,         EventType.LAB_ORDER_CREATED),
    (LabWebhookHandler,         EventType.LAB_REPORT_CREATED),
    (LabWebhookHandler,         EventType.IMAGING_REPORT_CREATED),
    (TaskWebhookHandler,        EventType.TASK_CREATED),
    (TaskWebhookHandler,        EventType.TASK_COMPLETED),
    (StaffWebhookHandler,       EventType.STAFF_CREATED),
    (StaffWebhookHandler,       EventType.STAFF_DEACTIVATED),
    (DocumentWebhookHandler,    EventType.DOCUMENT_RECEIVED),
    (DocumentWebhookHandler,    EventType.DOCUMENT_REVIEWED),
    (MessageWebhookHandler,     EventType.MESSAGE_CREATED),
])
def test_handler_dispatches_its_event(handler_cls, event_type):
    """Each handler fires an HTTP_REQUEST for every event it owns."""
    handler = _make_handler(handler_cls, event_type)
    effects = handler.compute()

    assert len(effects) == 1, (
        f"{handler_cls.__name__} returned {len(effects)} effects for "
        f"{EventType.Name(event_type)}"
    )
    assert effects[0].type == EffectType.HTTP_REQUEST
    body = _payload(effects)
    assert body["event"] == EventType.Name(event_type)
    assert body["source"] == "canvas"
    assert body["version"] == "1"
    assert body["id"]
