"""Optional names-and-details enrichment for webhook payloads."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.config_store import WebhookConfig
from canvas_event_webhooks.event_details import enrich_event, person_summary
from canvas_event_webhooks.handlers.base import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign_body
from canvas_event_webhooks.handlers.event_handlers import (
    AppointmentWebhookHandler,
    NoteWebhookHandler,
    PatientWebhookHandler,
)


class Staff:
    def __init__(self):
        self.id = "stf-1"
        self.first_name = "Jane"
        self.last_name = "Smith"
        self.prefix = "Dr."
        self.full_name = "Dr. Jane Smith"
        self.npi_number = "1234567890"
        self.credentialed_name = "Dr. Jane Smith MD"


class Patient:
    def __init__(self):
        self.id = "pt-1"
        self.first_name = "John"
        self.middle_name = ""
        self.last_name = "Doe"
        self.full_name = "John Doe"
        self.mrn = "999111"
        self.birth_date = "1980-01-15"
        self.sex_at_birth = "M"
        self.social_security_number = "111223333"


class Location:
    name = "Main Clinic"


class Appointment:
    def __init__(self):
        self.id = "appt-1"
        self.start_time = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)
        self.duration_minutes = 30
        self.status = "confirmed"
        self.description = "Follow-up"
        self.comment = None
        self.meeting_link = None
        self.provider = Staff()
        self.location = Location()
        self.patient = Patient()
        self.note_type = None


class Note:
    def __init__(self):
        self.title = "Office visit"
        self.body = {"phi": "do not leak this clinical text"}
        self.note_type = "office"
        self.datetime_of_service = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)
        self.place_of_service = "11"
        self.provider = Staff()
        self.supervising_provider = None
        self.location = Location()
        self.patient = Patient()


class CanvasUser:
    is_staff = True

    def __init__(self):
        self.staff = Staff()
        self.patient = None
        self.person_subclass = self.staff


def _event(event_type: int, *, instance=None, actor=None, context=None, target_id="rec-1"):
    event = Mock()
    event.type = event_type
    event.target = Mock()
    event.target.id = target_id
    event.target.type = None
    event.target.instance = instance
    event.context = context or {}
    event.actor = SimpleNamespace(instance=actor)
    return event


def _wh(*, include_details=False, secret="secret-a", name="A"):
    return WebhookConfig(
        id=name,
        name=name,
        url=f"https://{name}.example.com/hook",
        secret=secret,
        events=["APPOINTMENT_CREATED", "NOTE_CREATED", "PATIENT_CREATED"],
        include_details=include_details,
    )


def _http_effects(effects):
    return [e for e in effects if e.type == EffectType.HTTP_REQUEST]


def _body(effect) -> dict:
    data = json.loads(effect.payload)["data"]
    return json.loads(data["body"])


def _raw_body(effect) -> str:
    return json.loads(effect.payload)["data"]["body"]


def test_person_summary_includes_names_and_skips_ssn():
    summary = person_summary(Patient(), role="patient")
    assert summary["first_name"] == "John"
    assert summary["last_name"] == "Doe"
    assert summary["full_name"] == "John Doe"
    assert summary["mrn"] == "999111"
    assert "social_security_number" not in summary
    assert "111223333" not in json.dumps(summary)


def test_enrich_appointment_has_actor_patient_and_data():
    extra = enrich_event(
        _event(
            EventType.APPOINTMENT_CREATED,
            instance=Appointment(),
            actor=CanvasUser(),
            context={"patient": {"id": "pt-1"}},
        ),
        "APPOINTMENT_CREATED",
        "pt-1",
    )
    assert extra["patient"]["full_name"] == "John Doe"
    assert extra["patient"]["mrn"] == "999111"
    assert extra["actor"]["full_name"] == "Dr. Jane Smith"
    assert extra["data"]["status"] == "confirmed"
    assert extra["data"]["duration_minutes"] == 30
    assert extra["data"]["location"] == "Main Clinic"
    assert extra["data"]["provider"]["last_name"] == "Smith"
    assert "John Doe" in extra["description"]
    assert "Jane Smith" in extra["description"]
    dumped = json.dumps(extra)
    assert "111223333" not in dumped
    assert "social_security_number" not in dumped


def test_note_body_is_never_included():
    extra = enrich_event(
        _event(EventType.NOTE_CREATED, instance=Note(), actor=CanvasUser()),
        "NOTE_CREATED",
        "pt-1",
    )
    dumped = json.dumps(extra)
    assert "do not leak this clinical text" not in dumped
    assert extra["data"]["title"] == "Office visit"
    assert extra["data"]["note_type"] == "office"


def test_details_off_keeps_short_payload():
    handler = AppointmentWebhookHandler(
        event=_event(
            EventType.APPOINTMENT_CREATED,
            instance=Appointment(),
            actor=CanvasUser(),
            context={"patient": {"id": "pt-1"}},
        ),
        secrets={},
    )
    effects = _http_effects(handler._dispatch(webhooks=[_wh(include_details=False)]))
    body = _body(effects[0])
    assert "description" not in body
    assert "actor" not in body
    assert "patient" not in body
    assert "data" not in body
    assert body["event"] == "APPOINTMENT_CREATED"
    assert body["patient_id"] == "pt-1"


def test_details_on_includes_names():
    handler = AppointmentWebhookHandler(
        event=_event(
            EventType.APPOINTMENT_CREATED,
            instance=Appointment(),
            actor=CanvasUser(),
            context={"patient": {"id": "pt-1"}},
        ),
        secrets={},
    )
    effects = _http_effects(handler._dispatch(webhooks=[_wh(include_details=True)]))
    body = _body(effects[0])
    assert body["patient"]["full_name"] == "John Doe"
    assert body["actor"]["full_name"] == "Dr. Jane Smith"
    assert "Appointment Created" in body["description"]
    assert body["data"]["status"] == "confirmed"


def test_mixed_webhooks_sign_their_own_bodies():
    handler = AppointmentWebhookHandler(
        event=_event(
            EventType.APPOINTMENT_CREATED,
            instance=Appointment(),
            actor=CanvasUser(),
            context={"patient": {"id": "pt-1"}},
        ),
        secrets={},
    )
    short = _wh(include_details=False, secret="short-secret", name="short")
    rich = _wh(include_details=True, secret="rich-secret", name="rich")
    effects = _http_effects(handler._dispatch(webhooks=[short, rich]))
    assert len(effects) == 2
    bodies = [_body(e) for e in effects]
    short_body = next(b for b in bodies if "description" not in b)
    rich_body = next(b for b in bodies if "description" in b)
    assert "John Doe" not in json.dumps(short_body)
    assert rich_body["patient"]["full_name"] == "John Doe"

    for effect, secret in zip(effects, ["short-secret", "rich-secret"], strict=True):
        raw = _raw_body(effect)
        headers = json.loads(effect.payload)["data"]["headers"]
        ts = int(headers[TIMESTAMP_HEADER])
        assert headers[SIGNATURE_HEADER] == sign_body(secret, raw, ts)


def test_details_lookup_failure_still_delivers():
    handler = PatientWebhookHandler(
        event=_event(EventType.PATIENT_CREATED, instance=None, actor=None),
        secrets={},
    )
    effects = _http_effects(handler._dispatch(webhooks=[_wh(include_details=True)]))
    assert len(effects) == 1
    body = _body(effects[0])
    assert body["event"] == "PATIENT_CREATED"
    assert "description" in body
    assert body.get("patient") is None or "full_name" in (body.get("patient") or {})


def test_patient_id_is_not_fabricated_when_details_on():
    handler = NoteWebhookHandler(
        event=_event(EventType.NOTE_CREATED, instance=Note(), actor=CanvasUser(), context={}),
        secrets={},
    )
    body = _body(_http_effects(handler._dispatch(webhooks=[_wh(include_details=True)]))[0])
    # Note is patient-related; without context the id stays None rather than invented.
    assert body["patient_id"] is None
    assert body["patient"]["full_name"] == "John Doe"
