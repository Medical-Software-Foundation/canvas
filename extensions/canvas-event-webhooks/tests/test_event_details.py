"""Optional names-and-details enrichment for webhook payloads."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from canvas_event_webhooks.config_store import WebhookConfig
from canvas_event_webhooks.event_details import (
    _class_name,
    _codings,
    _plain,
    enrich_event,
    person_summary,
)
from canvas_event_webhooks.events_catalog import event_label
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


# ---------------------------------------------------------------------------
# Record extraction per Canvas model
# ---------------------------------------------------------------------------

STAFF_SUMMARY = {
    "id": "stf-1",
    "first_name": "Jane",
    "last_name": "Smith",
    "full_name": "Dr. Jane Smith",
    "type": "staff",
    "prefix": "Dr.",
    "npi": "1234567890",
    "credentialed_name": "Dr. Jane Smith MD",
}

PATIENT_SUMMARY = {
    "id": "pt-1",
    "first_name": "John",
    "last_name": "Doe",
    "full_name": "John Doe",
    "type": "patient",
    "mrn": "999111",
    "birth_date": "1980-01-15",
    "sex_at_birth": "M",
}

# Data extraction does not depend on the event name.
ANY_EVENT = "PATIENT_UPDATED"


def _model(class_name: str, **attrs):
    """Plain object whose class name matches a Canvas model, so its extractor runs."""
    instance = type(class_name, (), {})()
    instance.__dict__.update(attrs)
    return instance


class _Related:
    """Minimal stand-in for a Django related manager."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _details_event(instance=None, actor=None) -> SimpleNamespace:
    return SimpleNamespace(
        target=SimpleNamespace(instance=instance),
        actor=SimpleNamespace(instance=actor),
    )


def _coding():
    return _model("Coding", display="Lisinopril 10 MG Oral Tablet", code="314076")


def _task():
    return _model(
        "Task",
        title="Call patient back",
        status="OPEN",
        priority="high",
        due=date(2026, 9, 12),
        task_type="Task",
        tag="urgent",
        assignee=Staff(),
        creator=None,
    )


def _prescription():
    return _model(
        "Prescription",
        status="transmitted",
        medication=_model("Medication", codings=_Related([_coding()])),
        sig_original_input="Take 1 tablet by mouth daily",
        dose_quantity=1,
        dose_form="tablet",
        dose_route="oral",
        dose_frequency="daily",
        dispense_quantity=30,
        count_of_refills_allowed=0,
        pharmacy_name="Main Street Pharmacy",
        written_date=date(2026, 9, 1),
        prescriber=Staff(),
        is_refill=False,
        error_message=None,
    )


def _lab_order():
    return _model(
        "LabOrder",
        tests=_Related(
            [
                _model("LabTest", ontology_test_name="CBC"),
                _model("LabTest", ontology_test_name=None),
            ]
        ),
        date_ordered=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        requisition_number="REQ-1",
        ontology_lab_partner="Quest",
        comment=None,
        manual_processing_status="NEEDS_REVIEW",
        ordering_provider=Staff(),
    )


def _patient_record():
    patient = Patient()
    patient.active = True
    patient.nickname = "Johnny"
    return patient


def _staff_record():
    staff = Staff()
    staff.active = False
    return staff


def _coverage_with_unreadable_payer():
    class Coverage:
        state = "active"

        @property
        def transactor(self):
            raise ValueError("payer lookup failed")

    return Coverage()


@pytest.mark.parametrize(
    "instance,expected",
    [
        pytest.param(
            _model(
                "Appointment",
                start_time=datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc),
                duration_minutes=45,
                status="booked",
                comment="Bring insurance card",
                meeting_link="https://meet.example.com/abc",
                location=_model("PracticeLocation"),
                note_type=_model("NoteType"),
            ),
            {
                "record_type": "appointment",
                "start_time": "2026-09-02T14:00:00+00:00",
                "duration_minutes": 45,
                "status": "booked",
                "comment": "Bring insurance card",
                "meeting_link": "https://meet.example.com/abc",
            },
            id="appointment_with_unnamed_location_and_note_type",
        ),
        pytest.param(
            _task(),
            {
                "record_type": "task",
                "title": "Call patient back",
                "status": "OPEN",
                "priority": "high",
                "due": "2026-09-12",
                "task_type": "Task",
                "tag": "urgent",
                "assignee": STAFF_SUMMARY,
            },
            id="task",
        ),
        pytest.param(
            _model(
                "Note",
                title="Office visit",
                note_type="office",
                place_of_service="11",
                provider=Staff(),
                location=None,
            ),
            {
                "record_type": "note",
                "title": "Office visit",
                "note_type": "office",
                "place_of_service": "11",
                "provider": STAFF_SUMMARY,
            },
            id="note_without_location",
        ),
        pytest.param(
            _prescription(),
            {
                "record_type": "prescription",
                "status": "transmitted",
                "medication": "Lisinopril 10 MG Oral Tablet",
                "sig": "Take 1 tablet by mouth daily",
                "dose_quantity": 1,
                "dose_form": "tablet",
                "dose_route": "oral",
                "dose_frequency": "daily",
                "dispense_quantity": 30,
                "count_of_refills_allowed": 0,
                "pharmacy_name": "Main Street Pharmacy",
                "written_date": "2026-09-01",
                "prescriber": STAFF_SUMMARY,
                "is_refill": False,
            },
            id="prescription",
        ),
        pytest.param(
            _model(
                "Medication",
                status="active",
                codings=_Related([_coding()]),
                clinical_quantity_description="30 tablets",
                national_drug_code="00093-1234",
                start_date=date(2026, 1, 1),
                end_date=None,
            ),
            {
                "record_type": "medication",
                "status": "active",
                "codings": ["Lisinopril 10 MG Oral Tablet"],
                "clinical_quantity_description": "30 tablets",
                "national_drug_code": "00093-1234",
                "start_date": "2026-01-01",
            },
            id="medication",
        ),
        pytest.param(
            _lab_order(),
            {
                "record_type": "lab_order",
                "date_ordered": "2026-09-01T09:00:00+00:00",
                "requisition_number": "REQ-1",
                "lab_partner": "Quest",
                "manual_processing_status": "NEEDS_REVIEW",
                "ordering_provider": STAFF_SUMMARY,
                "tests": ["CBC"],
            },
            id="lab_order",
        ),
        pytest.param(
            _model("LabOrder", requisition_number="REQ-2"),
            {"record_type": "lab_order", "requisition_number": "REQ-2"},
            id="lab_order_without_tests_manager",
        ),
        pytest.param(
            _model(
                "LabReport",
                custom_document_name="CBC results",
                requisition_number="REQ-1",
                date_performed=date(2026, 9, 2),
                original_date=None,
                transmission_type="electronic",
                external_id="ext-9",
            ),
            {
                "record_type": "lab_report",
                "custom_document_name": "CBC results",
                "requisition_number": "REQ-1",
                "date_performed": "2026-09-02",
                "transmission_type": "electronic",
                "external_id": "ext-9",
            },
            id="lab_report",
        ),
        pytest.param(
            _model(
                "ImagingOrder",
                imaging="Chest X-ray",
                status="ordered",
                priority="routine",
                date_time_ordered=None,
                ordering_provider=None,
            ),
            {
                "record_type": "imaging_order",
                "imaging": "Chest X-ray",
                "status": "ordered",
                "priority": "routine",
            },
            id="imaging_order",
        ),
        pytest.param(
            _model(
                "ImagingReport",
                name=None,
                custom_document_name="MRI brain",
                status="final",
                original_date=date(2026, 8, 30),
            ),
            {
                "record_type": "imaging_report",
                "name": "MRI brain",
                "status": "final",
                "original_date": "2026-08-30",
            },
            id="imaging_report",
        ),
        pytest.param(
            _model(
                "Condition",
                clinical_status="active",
                onset_date=date(2020, 5, 1),
                resolution_date=None,
                codings=_Related([_model("Coding", code="I10")]),
                surgical=False,
            ),
            {
                "record_type": "condition",
                "clinical_status": "active",
                "onset_date": "2020-05-01",
                "codings": ["I10"],
                "surgical": False,
            },
            id="condition",
        ),
        pytest.param(
            _model(
                "AllergyIntolerance",
                status="active",
                severity="severe",
                category="medication",
                onset_date=None,
                codings=None,
            ),
            {
                "record_type": "allergy",
                "status": "active",
                "severity": "severe",
                "category": "medication",
            },
            id="allergy",
        ),
        pytest.param(
            _patient_record(),
            {**PATIENT_SUMMARY, "record_type": "patient", "active": True, "nickname": "Johnny"},
            id="patient",
        ),
        pytest.param(
            _staff_record(),
            {**STAFF_SUMMARY, "record_type": "staff", "active": False},
            id="staff",
        ),
        pytest.param(
            _model(
                "Message",
                read=False,
                sender=_model("CanvasUser", person_subclass=Patient()),
                recipient=Staff(),
            ),
            {
                "record_type": "message",
                "read": False,
                "sender": PATIENT_SUMMARY,
                "recipient": STAFF_SUMMARY,
            },
            id="message",
        ),
        pytest.param(
            _model("Letter", printed=True, staff=Staff()),
            {"record_type": "letter", "printed": True, "staff": STAFF_SUMMARY},
            id="letter",
        ),
        pytest.param(
            _model(
                "CareTeamMembership",
                status="active",
                staff=Staff(),
                role=_model("CareTeamRole", display="Primary care physician"),
            ),
            {
                "record_type": "care_team_membership",
                "status": "active",
                "staff": STAFF_SUMMARY,
                "role": "Primary care physician",
            },
            id="care_team_membership",
        ),
        pytest.param(
            _model("Claim", current_queue=None, queue="NeedsCodingReview", note_id=None),
            {"record_type": "claim", "current_queue": "NeedsCodingReview"},
            id="claim_without_note",
        ),
        pytest.param(
            _model(
                "Coverage",
                state="active",
                coverage_type=None,
                type="commercial",
                rank=1,
                transactor=_model("Transactor", name="Aetna"),
            ),
            {
                "record_type": "coverage",
                "state": "active",
                "coverage_type": "commercial",
                "rank": 1,
                "payer": "Aetna",
            },
            id="coverage",
        ),
        pytest.param(
            _model(
                "DocumentReference",
                status="current",
                document_content_type="application/pdf",
                business_identifier="doc-7",
            ),
            {
                "record_type": "document",
                "status": "current",
                "document_content_type": "application/pdf",
                "business_identifier": "doc-7",
            },
            id="document_reference",
        ),
        pytest.param(
            _model(
                "Observation",
                name="Blood pressure",
                status="final",
                description="x" * 300,
                note_type=_model("NoteType", name="Office visit"),
            ),
            {
                "record_type": "Observation",
                "name": "Blood pressure",
                "status": "final",
                "description": "x" * 239 + "…",
                "note_type": "Office visit",
            },
            id="unmapped_model_uses_generic_fields",
        ),
        pytest.param(
            _coverage_with_unreadable_payer(),
            {"record_type": "Coverage", "state": "active"},
            id="extractor_lookup_error_falls_back_to_generic",
        ),
    ],
)
def test_extracts_major_fields_by_record_type(instance, expected):
    extra = enrich_event(_details_event(instance), ANY_EVENT, None)

    assert extra["data"] == expected


@pytest.mark.parametrize(
    "event_name,instance,details",
    [
        pytest.param(
            "TASK_CREATED",
            _task(),
            '"Call patient back", due 2026-09-12, status OPEN, assigned to Dr. Jane Smith',
            id="task",
        ),
        pytest.param(
            "PRESCRIPTION_CREATED",
            _prescription(),
            '"Lisinopril 10 MG Oral Tablet", status transmitted, provider Dr. Jane Smith, '
            "pharmacy Main Street Pharmacy",
            id="prescription",
        ),
        pytest.param(
            "LAB_ORDER_CREATED",
            _lab_order(),
            "ordered 2026-09-01T09:00:00+00:00, provider Dr. Jane Smith",
            id="lab_order",
        ),
    ],
)
def test_description_summarises_key_record_fields(event_name, instance, details):
    extra = enrich_event(_details_event(instance), event_name, None)

    assert extra["description"] == f"Canvas — {event_label(event_name)} ({details})."


# ---------------------------------------------------------------------------
# Actor and patient resolution
# ---------------------------------------------------------------------------

class _PortalUser:
    """Patient login whose person_subclass cannot be read."""

    is_staff = False

    def __init__(self):
        self.patient = Patient()

    @property
    def person_subclass(self):
        raise TypeError("person_subclass unavailable")


class _StaffUserWithoutSubclass:
    is_staff = True
    person_subclass = None

    def __init__(self):
        self.staff = Staff()


class _UserWithUnreadableRole:
    """Only the user's own name fields can be read."""

    person_subclass = None
    first_name = "Sam"
    last_name = "Lee"

    @property
    def is_staff(self):
        raise TypeError("is_staff unavailable")


class _UserWithoutPerson:
    is_staff = False
    person_subclass = None
    patient = None


class _UnreadableEvent:
    @property
    def target(self):
        raise TypeError("target unavailable")

    @property
    def actor(self):
        raise TypeError("actor unavailable")


@pytest.mark.parametrize(
    "user,expected",
    [
        pytest.param(_PortalUser(), PATIENT_SUMMARY, id="patient_login_via_user_patient"),
        pytest.param(_StaffUserWithoutSubclass(), STAFF_SUMMARY, id="staff_login_via_user_staff"),
        pytest.param(
            _UserWithUnreadableRole(),
            {"first_name": "Sam", "last_name": "Lee", "full_name": "Sam Lee", "type": "staff"},
            id="falls_back_to_user_name",
        ),
    ],
)
def test_actor_resolution_fallbacks(user, expected):
    extra = enrich_event(_details_event(actor=user), ANY_EVENT, None)

    assert extra["actor"] == expected


def test_actor_omitted_when_user_has_no_person_record():
    extra = enrich_event(_details_event(actor=_UserWithoutPerson()), ANY_EVENT, None)

    assert extra == {"description": f"Canvas — {event_label(ANY_EVENT)}."}


def test_unreadable_event_target_and_actor_give_bare_description():
    extra = enrich_event(_UnreadableEvent(), ANY_EVENT, None)

    assert extra == {"description": f"Canvas — {event_label(ANY_EVENT)}."}


def test_patient_loaded_by_id_when_event_has_no_instance():
    with patch("canvas_sdk.v1.data.patient.Patient") as mock_patient_model:
        mock_patient_model.objects.filter.return_value.defer.return_value.first.return_value = (
            Patient()
        )

        extra = enrich_event(_details_event(), ANY_EVENT, "pt-1")

    assert mock_patient_model.mock_calls == [
        call.objects.filter(id="pt-1"),
        call.objects.filter().defer(
            "administrative_note", "clinical_note", "deceased_cause", "deceased_comment"
        ),
        call.objects.filter().defer().first(),
    ]
    assert extra["patient"] == PATIENT_SUMMARY
    assert extra["description"] == f"Canvas — {event_label(ANY_EVENT)} for patient John Doe."


def test_patient_lookup_error_omits_patient():
    with patch("canvas_sdk.v1.data.patient.Patient") as mock_patient_model:
        mock_patient_model.objects.filter.side_effect = TypeError("bad id")

        extra = enrich_event(_details_event(), ANY_EVENT, "pt-1")

    assert mock_patient_model.mock_calls == [call.objects.filter(id="pt-1")]
    assert "patient" not in extra


def test_unreadable_related_patient_is_omitted():
    class Letter:
        printed = True

        @property
        def patient(self):
            raise TypeError("patient unavailable")

    extra = enrich_event(_details_event(Letter()), ANY_EVENT, None)

    assert "patient" not in extra
    assert extra["data"] == {"record_type": "letter", "printed": True}


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

class RelatedObjectDoesNotExist(Exception):
    """Named like Django's error, which the plugin sandbox cannot import."""


def test_missing_related_record_degrades_to_label_description():
    class Appointment:
        @property
        def patient(self):
            raise RelatedObjectDoesNotExist("patient row deleted")

    with patch("canvas_event_webhooks.event_details.log") as mock_log:
        extra = enrich_event(_details_event(Appointment()), "APPOINTMENT_UPDATED", None)

    assert mock_log.mock_calls == [
        call.warning(
            "[Webhooks] Failed to attach event details (%s).", "RelatedObjectDoesNotExist"
        )
    ]
    assert extra == {"description": event_label("APPOINTMENT_UPDATED")}


def test_type_error_in_generic_fallback_degrades_to_label_description():
    class Task:
        @property
        def title(self):
            raise TypeError("title unavailable")

    with patch("canvas_event_webhooks.event_details.log") as mock_log:
        extra = enrich_event(_details_event(Task()), "TASK_UPDATED", None)

    assert mock_log.mock_calls == [
        call.warning("[Webhooks] Failed to attach event details (%s).", "TypeError")
    ]
    assert extra == {"description": event_label("TASK_UPDATED")}


def test_unexpected_error_during_enrichment_is_not_swallowed():
    class Appointment:
        @property
        def patient(self):
            raise RuntimeError("bug in lookup")

    with patch("canvas_event_webhooks.event_details.log") as mock_log:
        with pytest.raises(RuntimeError, match="bug in lookup"):
            enrich_event(_details_event(Appointment()), "APPOINTMENT_UPDATED", None)

    assert mock_log.mock_calls == []


def test_plain_falls_back_when_isoformat_or_str_fail():
    class BadIsoformat:
        def isoformat(self):
            raise ValueError("no isoformat")

        def __str__(self):
            return " fallback text "

    class Unprintable:
        def __str__(self):
            raise TypeError("no str")

    assert _plain(BadIsoformat()) == "fallback text"
    assert _plain(Unprintable()) is None
    assert _plain(True) is True


def test_class_name_ignores_none_and_mocks():
    mock = Mock()

    assert _class_name(None) == ""
    assert _class_name(mock) == ""
    assert mock.mock_calls == []
    assert _class_name(Staff()) == "Staff"


def test_codings_handles_unreadable_manager_and_blank_rows():
    class BrokenManager:
        def all(self):
            raise TypeError("manager unavailable")

    assert _codings(_model("Condition", codings=BrokenManager())) is None
    assert _codings(_model("Condition", codings=_Related([_model("Coding")]))) is None


# ---------------------------------------------------------------------------
# Query shape
# ---------------------------------------------------------------------------

def test_note_target_is_loaded_without_large_columns():
    note_model = type("Note", (), {"objects": Mock()})
    note_model.objects.filter.return_value.defer.return_value.first.return_value = _model(
        "Note", title="Office visit", note_type="office"
    )
    # No ``instance`` on the target: the SDK's full-row load must not be used.
    event = SimpleNamespace(
        target=SimpleNamespace(id="note-1", type=note_model),
        actor=SimpleNamespace(instance=None),
    )

    extra = enrich_event(event, "NOTE_UPDATED", None)

    assert note_model.objects.mock_calls == [
        call.filter(id="note-1"),
        call.filter().defer("body", "related_data", "billing_note"),
        call.filter().defer().first(),
    ]
    assert extra["data"] == {"record_type": "note", "title": "Office visit", "note_type": "office"}


def test_models_without_large_columns_use_the_sdk_target_instance():
    task_model = type("Task", (), {"objects": Mock()})
    event = SimpleNamespace(
        target=SimpleNamespace(id="task-1", type=task_model, instance=_task()),
        actor=SimpleNamespace(instance=None),
    )

    extra = enrich_event(event, "TASK_UPDATED", None)

    assert task_model.objects.mock_calls == []
    assert extra["data"]["title"] == "Call patient back"


def test_deferred_fields_exist_on_sdk_models():
    # A misspelled field would make .defer() raise at query time and drop the event.
    from django.apps import apps

    from canvas_event_webhooks.event_details import _DEFERRED_FIELDS

    for model_name, fields in _DEFERRED_FIELDS.items():
        field_names = {field.name for field in apps.get_model("v1", model_name)._meta.get_fields()}
        assert set(fields) <= field_names, model_name


def test_claim_note_id_is_read_without_loading_the_note():
    with patch("canvas_sdk.v1.data.note.Note") as mock_note_model:
        mock_note_model.objects.filter.return_value.values_list.return_value.first.return_value = (
            "note-1"
        )

        extra = enrich_event(
            _details_event(_model("Claim", queue="NeedsCodingReview", note_id=42)),
            "CLAIM_UPDATED",
            None,
        )

    assert mock_note_model.mock_calls == [
        call.objects.filter(dbid=42),
        call.objects.filter().values_list("id", flat=True),
        call.objects.filter().values_list().first(),
    ]
    assert extra["data"] == {
        "record_type": "claim",
        "current_queue": "NeedsCodingReview",
        "note_id": "note-1",
    }


def test_details_are_not_looked_up_for_webhooks_that_will_not_be_sent():
    unsigned = WebhookConfig(
        id="unsigned",
        name="unsigned",
        url="https://unsigned.example.com/hook",
        secret="",
        events=["APPOINTMENT_CREATED"],
        include_details=True,
    )
    internal = WebhookConfig(
        id="internal",
        name="internal",
        url="https://10.0.0.5/hook",
        secret="internal-secret",
        events=["APPOINTMENT_CREATED"],
        include_details=True,
    )
    handler = AppointmentWebhookHandler(
        event=_event(EventType.APPOINTMENT_CREATED, instance=Appointment(), actor=CanvasUser()),
        secrets={},
    )

    with patch("canvas_event_webhooks.handlers.base.enrich_event") as mock_enrich:
        effects = _http_effects(
            handler._dispatch(webhooks=[unsigned, internal, _wh(include_details=False, name="plain")])
        )

    assert mock_enrich.mock_calls == []
    assert [json.loads(e.payload)["data"]["url"] for e in effects] == ["https://plain.example.com/hook"]


def test_related_patient_is_loaded_by_fk_without_large_columns():
    with patch("canvas_sdk.v1.data.patient.Patient") as mock_patient_model:
        mock_patient_model.objects.filter.return_value.defer.return_value.first.return_value = (
            Patient()
        )

        extra = enrich_event(
            _details_event(_model("Task", title="Call patient back", patient_id=7)),
            "TASK_UPDATED",
            None,
        )

    assert mock_patient_model.mock_calls == [
        call.objects.filter(dbid=7),
        call.objects.filter().defer(
            "administrative_note", "clinical_note", "deceased_cause", "deceased_comment"
        ),
        call.objects.filter().defer().first(),
    ]
    assert extra["patient"] == PATIENT_SUMMARY


def test_claim_note_and_related_patient_queries_resolve_real_fields():
    # The lookups above are verified with mocks, which never resolve field names. Build the
    # real querysets (no database access) so a wrong name fails here, not in production.
    from canvas_sdk.v1.data.note import Note
    from canvas_sdk.v1.data.patient import Patient

    from canvas_event_webhooks.event_details import _DEFERRED_FIELDS

    note_ids = Note.objects.filter(dbid=1).values_list("id", flat=True)
    patients = Patient.objects.filter(dbid=1).defer(*_DEFERRED_FIELDS["Patient"])

    assert list(note_ids.query.values_select) == ["id"]
    assert set(patients.query.deferred_loading[0]) == set(_DEFERRED_FIELDS["Patient"])
