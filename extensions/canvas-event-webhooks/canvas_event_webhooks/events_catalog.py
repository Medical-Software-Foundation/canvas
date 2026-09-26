"""
Verified Canvas EventType catalog for the webhook plugin.

Event names are declared as strings, then resolved against
``canvas_sdk.events.EventType``. Names that are missing or not an int on
the host Canvas version are skipped so the plugin still loads (older
instances / sandboxes can expose some members as ``None``).

Command PRE/POST lifecycle hooks, search events, and UI-only events are
intentionally omitted — they are not useful as outbound webhooks.
"""

from __future__ import annotations

from canvas_sdk.events import EventType
from logger import log


def _resolve(name: str) -> int | None:
    """Return EventType int for ``name``, or None when unavailable here."""
    value = getattr(EventType, name, None)
    if not isinstance(value, int):
        return None
    try:
        if EventType.Name(value) != name:
            return None
    except (TypeError, ValueError):
        return None
    return value


def _n(event_type: object) -> str | None:
    """Map an EventType value to its name; None if it cannot be named."""
    if not isinstance(event_type, int):
        return None
    try:
        return EventType.Name(event_type)
    except (TypeError, ValueError):
        return None


def _events(pairs: list[tuple[str, str]]) -> list[tuple[int, str]]:
    """Keep only (EventType value, label) pairs that resolve on this host."""
    out: list[tuple[int, str]] = []
    for name, label in pairs:
        value = _resolve(name)
        if value is not None:
            out.append((value, label))
    return out


# ---------------------------------------------------------------------------
# Categories — order is the UI display order
# ---------------------------------------------------------------------------

_RAW_CATEGORIES: list[dict] = [
    {
        "key": "patients",
        "label": "Patients",
        "events": [
            ("PATIENT_CREATED", "Patient Created"),
            ("PATIENT_UPDATED", "Patient Updated"),
            ("PATIENT_ADDRESS_CREATED", "Patient Address Created"),
            ("PATIENT_ADDRESS_UPDATED", "Patient Address Updated"),
            ("PATIENT_ADDRESS_DELETED", "Patient Address Deleted"),
            ("PATIENT_CONTACT_POINT_CREATED", "Patient Contact Point Created"),
            ("PATIENT_CONTACT_POINT_UPDATED", "Patient Contact Point Updated"),
            ("PATIENT_CONTACT_POINT_DELETED", "Patient Contact Point Deleted"),
            ("PATIENT_CONTACT_PERSON_CREATED", "Patient Contact Person Created"),
            ("PATIENT_CONTACT_PERSON_UPDATED", "Patient Contact Person Updated"),
            ("PATIENT_CONTACT_PERSON_DELETED", "Patient Contact Person Deleted"),
            ("PATIENT_EXTERNAL_IDENTIFIER_CREATED", "Patient External Identifier Created"),
            ("PATIENT_EXTERNAL_IDENTIFIER_UPDATED", "Patient External Identifier Updated"),
            ("PATIENT_EXTERNAL_IDENTIFIER_DELETED", "Patient External Identifier Deleted"),
            ("PATIENT_FACILITY_ADDRESS_CREATED", "Patient Facility Address Created"),
            ("PATIENT_FACILITY_ADDRESS_UPDATED", "Patient Facility Address Updated"),
            ("PATIENT_FACILITY_ADDRESS_DELETED", "Patient Facility Address Deleted"),
            ("PATIENT_METADATA_CREATED", "Patient Metadata Created"),
            ("PATIENT_METADATA_UPDATED", "Patient Metadata Updated"),
            ("PATIENT_PREFERRED_PHARMACY_UPDATED", "Patient Preferred Pharmacy Updated"),
            ("PATIENT_PAYMENT_PROCESSED", "Patient Payment Processed"),
        ],
    },
    {
        "key": "appointments",
        "label": "Appointments",
        "events": [
            ("APPOINTMENT_CREATED", "Appointment Created"),
            ("APPOINTMENT_UPDATED", "Appointment Updated"),
            ("APPOINTMENT_RESCHEDULED", "Appointment Rescheduled"),
            ("APPOINTMENT_CHECKED_IN", "Appointment Checked In"),
            ("APPOINTMENT_CANCELED", "Appointment Canceled"),
            ("APPOINTMENT_NO_SHOWED", "Appointment No-Showed"),
            ("APPOINTMENT_RESTORED", "Appointment Restored"),
            ("APPOINTMENT_LABEL_ADDED", "Appointment Label Added"),
            ("APPOINTMENT_LABEL_REMOVED", "Appointment Label Removed"),
            ("APPOINTMENT_METADATA_CREATED", "Appointment Metadata Created"),
            ("APPOINTMENT_METADATA_UPDATED", "Appointment Metadata Updated"),
        ],
    },
    {
        "key": "notes",
        "label": "Clinical Notes",
        "events": [
            ("NOTE_CREATED", "Note Created"),
            ("NOTE_UPDATED", "Note Updated"),
            ("NOTE_OPENED", "Note Opened"),
            ("NOTE_CLOSED", "Note Closed"),
            ("NOTE_STATE_CHANGE_EVENT_CREATED", "Note State Changed"),
            ("NOTE_STATE_CHANGE_EVENT_UPDATED", "Note State Change Updated"),
            ("NOTE_SUPERVISING_PROVIDER_CHANGED", "Note Supervising Provider Changed"),
            ("NOTE_METADATA_CREATED", "Note Metadata Created"),
            ("NOTE_METADATA_UPDATED", "Note Metadata Updated"),
            ("ENCOUNTER_CREATED", "Encounter Created"),
            ("ENCOUNTER_UPDATED", "Encounter Updated"),
        ],
    },
    {
        "key": "clinical",
        "label": "Clinical Records",
        "events": [
            ("CONDITION_CREATED", "Condition Created"),
            ("CONDITION_UPDATED", "Condition Updated"),
            ("CONDITION_RESOLVED", "Condition Resolved"),
            ("CONDITION_ASSESSED", "Condition Assessed"),
            ("ALLERGY_INTOLERANCE_CREATED", "Allergy Intolerance Created"),
            ("ALLERGY_INTOLERANCE_UPDATED", "Allergy Intolerance Updated"),
            ("IMMUNIZATION_CREATED", "Immunization Created"),
            ("IMMUNIZATION_UPDATED", "Immunization Updated"),
            ("IMMUNIZATION_STATEMENT_CREATED", "Immunization Statement Created"),
            ("IMMUNIZATION_STATEMENT_UPDATED", "Immunization Statement Updated"),
            ("OBSERVATION_CREATED", "Observation Created"),
            ("OBSERVATION_UPDATED", "Observation Updated"),
            ("VITAL_SIGN_CREATED", "Vital Sign Created"),
            ("VITAL_SIGN_UPDATED", "Vital Sign Updated"),
            ("INSTRUCTION_CREATED", "Instruction Created"),
            ("INSTRUCTION_UPDATED", "Instruction Updated"),
            ("INTERVIEW_CREATED", "Interview Created"),
            ("INTERVIEW_UPDATED", "Interview Updated"),
            ("DEVICE_CREATED", "Device Created"),
            ("DEVICE_UPDATED", "Device Updated"),
            ("DETECTED_ISSUE_CREATED", "Detected Issue Created"),
            ("DETECTED_ISSUE_UPDATED", "Detected Issue Updated"),
            ("DETECTED_ISSUE_EVIDENCE_CREATED", "Detected Issue Evidence Created"),
            ("DETECTED_ISSUE_EVIDENCE_UPDATED", "Detected Issue Evidence Updated"),
        ],
    },
    {
        "key": "medications",
        "label": "Medications",
        "events": [
            ("MEDICATION_LIST_ITEM_CREATED", "Medication List Item Created"),
            ("MEDICATION_LIST_ITEM_UPDATED", "Medication List Item Updated"),
            ("COMPOUND_MEDICATION_CREATED", "Compound Medication Created"),
            ("COMPOUND_MEDICATION_UPDATED", "Compound Medication Updated"),
        ],
    },
    {
        "key": "prescriptions",
        "label": "Prescriptions",
        "events": [
            ("PRESCRIPTION_CREATED", "Prescription Created"),
            ("PRESCRIPTION_UPDATED", "Prescription Updated"),
            ("PRESCRIPTION_SIGNED", "Prescription Signed"),
            ("PRESCRIPTION_TRANSMITTED", "Prescription Transmitted"),
            ("PRESCRIPTION_DELIVERED", "Prescription Delivered"),
            ("PRESCRIPTION_ACCEPTED", "Prescription Accepted"),
            ("PRESCRIPTION_ERRORED", "Prescription Errored"),
            ("PRESCRIPTION_CANCELED", "Prescription Canceled"),
            ("PRESCRIPTION_CANCEL_REQUESTED", "Prescription Cancel Requested"),
            ("PRESCRIPTION_CANCEL_DENIED", "Prescription Cancel Denied"),
            ("PRESCRIPTION_PENDING", "Prescription Pending"),
            ("PRESCRIPTION_INQUEUE", "Prescription In Queue"),
            ("PRESCRIPTION_OPENED", "Prescription Opened"),
            ("PRESCRIPTION_RECEIVED", "Prescription Received"),
        ],
    },
    {
        "key": "labs",
        "label": "Labs & Imaging",
        "events": [
            ("LAB_ORDER_CREATED", "Lab Order Created"),
            ("LAB_ORDER_UPDATED", "Lab Order Updated"),
            ("LAB_REPORT_CREATED", "Lab Report Created"),
            ("LAB_REPORT_UPDATED", "Lab Report Updated"),
            ("IMAGING_REPORT_CREATED", "Imaging Report Created"),
            ("IMAGING_REPORT_UPDATED", "Imaging Report Updated"),
            ("REFERRAL_REPORT_CREATED", "Referral Report Created"),
            ("REFERRAL_REPORT_UPDATED", "Referral Report Updated"),
        ],
    },
    {
        "key": "tasks",
        "label": "Tasks",
        "events": [
            ("TASK_CREATED", "Task Created"),
            ("TASK_UPDATED", "Task Updated"),
            ("TASK_COMPLETED", "Task Completed"),
            ("TASK_CLOSED", "Task Closed"),
            ("TASK_COMMENT_CREATED", "Task Comment Created"),
            ("TASK_COMMENT_UPDATED", "Task Comment Updated"),
            ("TASK_COMMENT_DELETED", "Task Comment Deleted"),
            ("TASK_LABELS_ADJUSTED", "Task Labels Adjusted"),
            ("TASK_METADATA_CREATED", "Task Metadata Created"),
            ("TASK_METADATA_UPDATED", "Task Metadata Updated"),
        ],
    },
    {
        "key": "staff",
        "label": "Staff",
        "events": [
            ("STAFF_CREATED", "Staff Created"),
            ("STAFF_UPDATED", "Staff Updated"),
            ("STAFF_ACTIVATED", "Staff Activated"),
            ("STAFF_DEACTIVATED", "Staff Deactivated"),
            ("STAFF_EXTERNAL_IDENTIFIER_CREATED", "Staff External Identifier Created"),
            ("STAFF_EXTERNAL_IDENTIFIER_UPDATED", "Staff External Identifier Updated"),
            ("STAFF_EXTERNAL_IDENTIFIER_DELETED", "Staff External Identifier Deleted"),
            ("STAFF_METADATA_CREATED", "Staff Metadata Created"),
            ("STAFF_METADATA_UPDATED", "Staff Metadata Updated"),
            ("STAFF_METADATA_DELETED", "Staff Metadata Deleted"),
        ],
    },
    {
        "key": "documents",
        "label": "Documents",
        "events": [
            ("DOCUMENT_RECEIVED", "Document Received"),
            ("DOCUMENT_LINKED_TO_PATIENT", "Document Linked to Patient"),
            ("DOCUMENT_CATEGORIZED", "Document Categorized"),
            ("DOCUMENT_REVIEWED", "Document Reviewed"),
            ("DOCUMENT_DELETED", "Document Deleted"),
            ("DOCUMENT_DELEGATED", "Document Delegated"),
            ("DOCUMENT_FIELDS_UPDATED", "Document Fields Updated"),
            ("DOCUMENT_REVIEWER_ASSIGNED", "Document Reviewer Assigned"),
            ("DOCUMENT_REFERENCE_CREATED", "Document Reference Created"),
            ("DOCUMENT_REFERENCE_UPDATED", "Document Reference Updated"),
            ("DOCUMENT_REFERENCE_DELETED", "Document Reference Deleted"),
        ],
    },
    {
        "key": "messages",
        "label": "Messages & Letters",
        "events": [
            ("MESSAGE_CREATED", "Message Created"),
            ("MESSAGE_TRANSMISSION_CREATED", "Message Transmission Created"),
            ("MESSAGE_TRANSMISSION_UPDATED", "Message Transmission Updated"),
            ("LETTER_CREATED", "Letter Created"),
            ("LETTER_UPDATED", "Letter Updated"),
            ("LETTER_ACTION_EVENT_CREATED", "Letter Action Created"),
            ("LETTER_ACTION_EVENT_UPDATED", "Letter Action Updated"),
        ],
    },
    {
        "key": "care_teams",
        "label": "Care Teams & Groups",
        "events": [
            ("CARE_TEAM_MEMBERSHIP_CREATED", "Care Team Membership Created"),
            ("CARE_TEAM_MEMBERSHIP_UPDATED", "Care Team Membership Updated"),
            ("CARE_TEAM_MEMBERSHIP_DELETED", "Care Team Membership Deleted"),
            ("PATIENT_GROUP_CREATED", "Patient Group Created"),
            ("PATIENT_GROUP_UPDATED", "Patient Group Updated"),
            ("PATIENT_GROUP_MEMBERSHIP_CREATED", "Patient Group Membership Created"),
            ("PATIENT_GROUP_MEMBERSHIP_UPDATED", "Patient Group Membership Updated"),
            ("PATIENT_GROUP_MEMBERSHIP_DELETED", "Patient Group Membership Deleted"),
        ],
    },
    {
        "key": "billing",
        "label": "Billing, Coverage & Consent",
        "events": [
            ("BILLING_LINE_ITEM_CREATED", "Billing Line Item Created"),
            ("BILLING_LINE_ITEM_UPDATED", "Billing Line Item Updated"),
            ("CLAIM_CREATED", "Claim Created"),
            ("CLAIM_UPDATED", "Claim Updated"),
            ("CLAIM_INCIDENT_TO_CHANGED", "Claim Incident-To Changed"),
            ("CLAIM_QUEUE_MOVED", "Claim Queue Moved"),
            ("CLAIM_SUPERVISING_PROVIDER_CHANGED", "Claim Supervising Provider Changed"),
            ("COVERAGE_CREATED", "Coverage Created"),
            ("COVERAGE_UPDATED", "Coverage Updated"),
            ("COVERAGE_ELIGIBILITY_RESPONSE_CREATED", "Coverage Eligibility Response Created"),
            ("COVERAGE_ELIGIBILITY_RESPONSE_UPDATED", "Coverage Eligibility Response Updated"),
            ("COVERAGE_ELIGIBILITY_RESPONSE_ACTIVE", "Coverage Eligibility Response Active"),
            ("COVERAGE_ELIGIBILITY_RESPONSE_FAILED", "Coverage Eligibility Response Failed"),
            ("COVERAGE_ELIGIBILITY_RESPONSE_INACTIVE", "Coverage Eligibility Response Inactive"),
            ("CONSENT_CREATED", "Consent Created"),
            ("CONSENT_UPDATED", "Consent Updated"),
            ("CONSENT_DELETED", "Consent Deleted"),
        ],
    },
]

CATEGORIES: list[dict] = [
    {
        "key": category["key"],
        "label": category["label"],
        "events": _events(category["events"]),
    }
    for category in _RAW_CATEGORIES
]

# Say so at load time. Without this an event silently disappears from the UI and
# stops firing, which looks identical to a broken webhook from the admin's side.
_UNAVAILABLE: list[str] = [
    name
    for category in _RAW_CATEGORIES
    for name, _label in category["events"]
    if _resolve(name) is None
]
if _UNAVAILABLE:
    log.info(
        "[Webhooks] %d catalogued event(s) are not available on this Canvas "
        "version and were left out of the catalog: %s",
        len(_UNAVAILABLE),
        ", ".join(_UNAVAILABLE),
    )


# Events that are not about a specific patient. Everything else in the catalog
# is treated as patient-related and MUST include a top-level patient_id.
_NON_PATIENT_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "STAFF_CREATED",
        "STAFF_UPDATED",
        "STAFF_ACTIVATED",
        "STAFF_DEACTIVATED",
        "STAFF_EXTERNAL_IDENTIFIER_CREATED",
        "STAFF_EXTERNAL_IDENTIFIER_UPDATED",
        "STAFF_EXTERNAL_IDENTIFIER_DELETED",
        "STAFF_METADATA_CREATED",
        "STAFF_METADATA_UPDATED",
        "STAFF_METADATA_DELETED",
        "PATIENT_GROUP_CREATED",
        "PATIENT_GROUP_UPDATED",
        "COMPOUND_MEDICATION_CREATED",
        "COMPOUND_MEDICATION_UPDATED",
    }
)


def all_event_names() -> list[str]:
    """Return every catalogued event name, in display order."""
    names: list[str] = []
    for category in CATEGORIES:
        for event_type, _label in category["events"]:
            name = _n(event_type)
            if name is not None:
                names.append(name)
    return names


def event_type_names(category_key: str) -> list[str]:
    """Return EventType.Name strings for a category (used as RESPONDS_TO)."""
    for category in CATEGORIES:
        if category["key"] == category_key:
            names: list[str] = []
            for event_type, _label in category["events"]:
                name = _n(event_type)
                if name is not None:
                    names.append(name)
            return names
    raise KeyError(f"Unknown event category: {category_key}")


def is_patient_related(event_name: str) -> bool:
    """True when the event is about a patient and must carry patient_id."""
    return event_name not in _NON_PATIENT_EVENT_NAMES and event_name in _ALL_EVENT_NAMES_SET


def known_event(event_name: str) -> bool:
    return event_name in _ALL_EVENT_NAMES_SET


def event_label(event_name: str) -> str:
    """Human-readable label for a catalogued event name."""
    return _EVENT_LABELS.get(event_name) or event_name.replace("_", " ").title()


def catalog_for_ui() -> list[dict]:
    """JSON-serialisable catalog: categories with name/label pairs."""
    out: list[dict] = []
    for category in CATEGORIES:
        events = []
        for event_type, label in category["events"]:
            name = _n(event_type)
            if name is not None:
                events.append({"name": name, "label": label})
        out.append(
            {
                "key": category["key"],
                "label": category["label"],
                "events": events,
            }
        )
    return out


_ALL_EVENT_NAMES_SET: frozenset[str] = frozenset(all_event_names())
_NON_PATIENT_EVENTS: frozenset[str] = frozenset(
    name for name in _NON_PATIENT_EVENT_NAMES if name in _ALL_EVENT_NAMES_SET
)
_EVENT_LABELS: dict[str, str] = {
    name: label
    for category in CATEGORIES
    for event_type, label in category["events"]
    if (name := _n(event_type)) is not None
}
PATIENT_RELATED: frozenset[str] = frozenset(
    name for name in _ALL_EVENT_NAMES_SET if name not in _NON_PATIENT_EVENTS
)
