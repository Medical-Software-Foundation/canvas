"""Catalog integrity: only real EventType names, no invented events."""

from __future__ import annotations

from canvas_sdk.events import EventType

from canvas_event_webhooks.events_catalog import (
    CATEGORIES,
    PATIENT_RELATED,
    all_event_names,
    catalog_for_ui,
    event_label,
    event_type_names,
    is_patient_related,
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

INVENTED = [
    "PATIENT_DELETED",
    "PATIENT_ACTIVATED",
    "PATIENT_DEACTIVATED",
    "APPOINTMENT_DELETED",
    "APPOINTMENT_COMPLETED",
    "TASK_DELETED",
    "MESSAGE_UPDATED",
    "MESSAGE_SENT",
    "MESSAGE_DELETED",
    "CONVERSATION_CREATED",
    "PRESCRIPTION_RENEWED",
    "PRESCRIPTION_REJECTED",
    "PRESCRIPTION_SENT",
]

HANDLERS_BY_CATEGORY = {
    "patients": PatientWebhookHandler,
    "appointments": AppointmentWebhookHandler,
    "notes": NoteWebhookHandler,
    "clinical": ClinicalWebhookHandler,
    "medications": MedicationWebhookHandler,
    "prescriptions": PrescriptionWebhookHandler,
    "labs": LabWebhookHandler,
    "tasks": TaskWebhookHandler,
    "staff": StaffWebhookHandler,
    "documents": DocumentWebhookHandler,
    "messages": MessageWebhookHandler,
    "care_teams": CareTeamWebhookHandler,
    "billing": BillingWebhookHandler,
}


def test_every_catalog_event_exists_on_event_type():
    known = set(EventType.keys())
    for name in all_event_names():
        assert name in known, name


def test_invented_events_are_not_in_the_catalog():
    names = set(all_event_names())
    for fake in INVENTED:
        assert fake not in names


def test_no_duplicate_catalog_events():
    names = all_event_names()
    assert len(names) == len(set(names))
    assert len(names) > 40


def test_handler_responds_to_matches_catalog():
    for key, handler in HANDLERS_BY_CATEGORY.items():
        assert handler.RESPONDS_TO == event_type_names(key)


def test_ui_catalog_covers_every_event():
    ui_names = [e["name"] for cat in catalog_for_ui() for e in cat["events"]]
    assert ui_names == all_event_names()


def test_patient_related_set_excludes_staff():
    assert "STAFF_CREATED" not in PATIENT_RELATED
    assert "PATIENT_CREATED" in PATIENT_RELATED
    assert is_patient_related("PRESCRIPTION_CREATED")
    assert not is_patient_related("STAFF_DEACTIVATED")


def test_category_keys_match_handlers():
    keys = [c["key"] for c in CATEGORIES]
    assert set(keys) == set(HANDLERS_BY_CATEGORY)


def test_event_label_uses_catalog():
    assert event_label("APPOINTMENT_CREATED") == "Appointment Created"
    assert event_label("UNKNOWN_EVENT_XYZ") == "Unknown Event Xyz"


def test_event_type_names_rejects_unknown_category():
    try:
        event_type_names("not_a_category")
    except KeyError as exc:
        assert "not_a_category" in str(exc)
    else:
        raise AssertionError("expected KeyError for an unknown category")


def test_catalog_skips_unavailable_event_types(monkeypatch):
    """Host EventType members that are None must not crash import / catalog build."""
    import canvas_event_webhooks.events_catalog as catalog

    original = catalog._resolve

    def fake_resolve(name: str):
        if name == "PATIENT_CREATED":
            return None
        return original(name)

    monkeypatch.setattr(catalog, "_resolve", fake_resolve)
    events = catalog._events([("PATIENT_CREATED", "Patient Created"), ("PATIENT_UPDATED", "Patient Updated")])
    names = [catalog._n(value) for value, _ in events]
    assert "PATIENT_CREATED" not in names
    assert "PATIENT_UPDATED" in names
    assert catalog._n(None) is None
