"""
Verified Canvas EventType catalog for the webhook plugin.

Every event listed here exists on ``canvas_sdk.events.EventType`` (checked at
import time via ``EventType.Name(EventType.<NAME>)``). Command PRE/POST
lifecycle hooks, search events, and UI-only events are intentionally omitted
— they are not useful as outbound webhooks.

Do not add event names that cannot be resolved against EventType.
"""

from __future__ import annotations

from canvas_sdk.events import EventType


def _n(event_type: int) -> str:
    return EventType.Name(event_type)


# ---------------------------------------------------------------------------
# Categories — order is the UI display order
# ---------------------------------------------------------------------------

CATEGORIES: list[dict] = [
    {
        "key": "patients",
        "label": "Patients",
        "events": [
            (EventType.PATIENT_CREATED, "Patient Created"),
            (EventType.PATIENT_UPDATED, "Patient Updated"),
            (EventType.PATIENT_ADDRESS_CREATED, "Patient Address Created"),
            (EventType.PATIENT_ADDRESS_UPDATED, "Patient Address Updated"),
            (EventType.PATIENT_ADDRESS_DELETED, "Patient Address Deleted"),
            (EventType.PATIENT_CONTACT_POINT_CREATED, "Patient Contact Point Created"),
            (EventType.PATIENT_CONTACT_POINT_UPDATED, "Patient Contact Point Updated"),
            (EventType.PATIENT_CONTACT_POINT_DELETED, "Patient Contact Point Deleted"),
            (EventType.PATIENT_CONTACT_PERSON_CREATED, "Patient Contact Person Created"),
            (EventType.PATIENT_CONTACT_PERSON_UPDATED, "Patient Contact Person Updated"),
            (EventType.PATIENT_CONTACT_PERSON_DELETED, "Patient Contact Person Deleted"),
            (EventType.PATIENT_EXTERNAL_IDENTIFIER_CREATED, "Patient External Identifier Created"),
            (EventType.PATIENT_EXTERNAL_IDENTIFIER_UPDATED, "Patient External Identifier Updated"),
            (EventType.PATIENT_EXTERNAL_IDENTIFIER_DELETED, "Patient External Identifier Deleted"),
            (EventType.PATIENT_FACILITY_ADDRESS_CREATED, "Patient Facility Address Created"),
            (EventType.PATIENT_FACILITY_ADDRESS_UPDATED, "Patient Facility Address Updated"),
            (EventType.PATIENT_FACILITY_ADDRESS_DELETED, "Patient Facility Address Deleted"),
            (EventType.PATIENT_METADATA_CREATED, "Patient Metadata Created"),
            (EventType.PATIENT_METADATA_UPDATED, "Patient Metadata Updated"),
            (EventType.PATIENT_PREFERRED_PHARMACY_UPDATED, "Patient Preferred Pharmacy Updated"),
            (EventType.PATIENT_PAYMENT_PROCESSED, "Patient Payment Processed"),
        ],
    },
    {
        "key": "appointments",
        "label": "Appointments",
        "events": [
            (EventType.APPOINTMENT_CREATED, "Appointment Created"),
            (EventType.APPOINTMENT_UPDATED, "Appointment Updated"),
            (EventType.APPOINTMENT_RESCHEDULED, "Appointment Rescheduled"),
            (EventType.APPOINTMENT_CHECKED_IN, "Appointment Checked In"),
            (EventType.APPOINTMENT_CANCELED, "Appointment Canceled"),
            (EventType.APPOINTMENT_NO_SHOWED, "Appointment No-Showed"),
            (EventType.APPOINTMENT_RESTORED, "Appointment Restored"),
            (EventType.APPOINTMENT_LABEL_ADDED, "Appointment Label Added"),
            (EventType.APPOINTMENT_LABEL_REMOVED, "Appointment Label Removed"),
            (EventType.APPOINTMENT_METADATA_CREATED, "Appointment Metadata Created"),
            (EventType.APPOINTMENT_METADATA_UPDATED, "Appointment Metadata Updated"),
        ],
    },
    {
        "key": "notes",
        "label": "Clinical Notes",
        "events": [
            (EventType.NOTE_CREATED, "Note Created"),
            (EventType.NOTE_UPDATED, "Note Updated"),
            (EventType.NOTE_OPENED, "Note Opened"),
            (EventType.NOTE_CLOSED, "Note Closed"),
            (EventType.NOTE_STATE_CHANGE_EVENT_CREATED, "Note State Changed"),
            (EventType.NOTE_STATE_CHANGE_EVENT_UPDATED, "Note State Change Updated"),
            (EventType.NOTE_SUPERVISING_PROVIDER_CHANGED, "Note Supervising Provider Changed"),
            (EventType.NOTE_METADATA_CREATED, "Note Metadata Created"),
            (EventType.NOTE_METADATA_UPDATED, "Note Metadata Updated"),
            (EventType.ENCOUNTER_CREATED, "Encounter Created"),
            (EventType.ENCOUNTER_UPDATED, "Encounter Updated"),
        ],
    },
    {
        "key": "clinical",
        "label": "Clinical Records",
        "events": [
            (EventType.CONDITION_CREATED, "Condition Created"),
            (EventType.CONDITION_UPDATED, "Condition Updated"),
            (EventType.CONDITION_RESOLVED, "Condition Resolved"),
            (EventType.CONDITION_ASSESSED, "Condition Assessed"),
            (EventType.ALLERGY_INTOLERANCE_CREATED, "Allergy Intolerance Created"),
            (EventType.ALLERGY_INTOLERANCE_UPDATED, "Allergy Intolerance Updated"),
            (EventType.IMMUNIZATION_CREATED, "Immunization Created"),
            (EventType.IMMUNIZATION_UPDATED, "Immunization Updated"),
            (EventType.IMMUNIZATION_STATEMENT_CREATED, "Immunization Statement Created"),
            (EventType.IMMUNIZATION_STATEMENT_UPDATED, "Immunization Statement Updated"),
            (EventType.OBSERVATION_CREATED, "Observation Created"),
            (EventType.OBSERVATION_UPDATED, "Observation Updated"),
            (EventType.VITAL_SIGN_CREATED, "Vital Sign Created"),
            (EventType.VITAL_SIGN_UPDATED, "Vital Sign Updated"),
            (EventType.INSTRUCTION_CREATED, "Instruction Created"),
            (EventType.INSTRUCTION_UPDATED, "Instruction Updated"),
            (EventType.INTERVIEW_CREATED, "Interview Created"),
            (EventType.INTERVIEW_UPDATED, "Interview Updated"),
            (EventType.DEVICE_CREATED, "Device Created"),
            (EventType.DEVICE_UPDATED, "Device Updated"),
            (EventType.DETECTED_ISSUE_CREATED, "Detected Issue Created"),
            (EventType.DETECTED_ISSUE_UPDATED, "Detected Issue Updated"),
            (EventType.DETECTED_ISSUE_EVIDENCE_CREATED, "Detected Issue Evidence Created"),
            (EventType.DETECTED_ISSUE_EVIDENCE_UPDATED, "Detected Issue Evidence Updated"),
        ],
    },
    {
        "key": "medications",
        "label": "Medications",
        "events": [
            (EventType.MEDICATION_LIST_ITEM_CREATED, "Medication List Item Created"),
            (EventType.MEDICATION_LIST_ITEM_UPDATED, "Medication List Item Updated"),
            (EventType.COMPOUND_MEDICATION_CREATED, "Compound Medication Created"),
            (EventType.COMPOUND_MEDICATION_UPDATED, "Compound Medication Updated"),
        ],
    },
    {
        "key": "prescriptions",
        "label": "Prescriptions",
        "events": [
            (EventType.PRESCRIPTION_CREATED, "Prescription Created"),
            (EventType.PRESCRIPTION_UPDATED, "Prescription Updated"),
            (EventType.PRESCRIPTION_SIGNED, "Prescription Signed"),
            (EventType.PRESCRIPTION_TRANSMITTED, "Prescription Transmitted"),
            (EventType.PRESCRIPTION_DELIVERED, "Prescription Delivered"),
            (EventType.PRESCRIPTION_ACCEPTED, "Prescription Accepted"),
            (EventType.PRESCRIPTION_ERRORED, "Prescription Errored"),
            (EventType.PRESCRIPTION_CANCELED, "Prescription Canceled"),
            (EventType.PRESCRIPTION_CANCEL_REQUESTED, "Prescription Cancel Requested"),
            (EventType.PRESCRIPTION_CANCEL_DENIED, "Prescription Cancel Denied"),
            (EventType.PRESCRIPTION_PENDING, "Prescription Pending"),
            (EventType.PRESCRIPTION_INQUEUE, "Prescription In Queue"),
            (EventType.PRESCRIPTION_OPENED, "Prescription Opened"),
            (EventType.PRESCRIPTION_RECEIVED, "Prescription Received"),
        ],
    },
    {
        "key": "labs",
        "label": "Labs & Imaging",
        "events": [
            (EventType.LAB_ORDER_CREATED, "Lab Order Created"),
            (EventType.LAB_ORDER_UPDATED, "Lab Order Updated"),
            (EventType.LAB_REPORT_CREATED, "Lab Report Created"),
            (EventType.LAB_REPORT_UPDATED, "Lab Report Updated"),
            (EventType.IMAGING_REPORT_CREATED, "Imaging Report Created"),
            (EventType.IMAGING_REPORT_UPDATED, "Imaging Report Updated"),
            (EventType.REFERRAL_REPORT_CREATED, "Referral Report Created"),
            (EventType.REFERRAL_REPORT_UPDATED, "Referral Report Updated"),
        ],
    },
    {
        "key": "tasks",
        "label": "Tasks",
        "events": [
            (EventType.TASK_CREATED, "Task Created"),
            (EventType.TASK_UPDATED, "Task Updated"),
            (EventType.TASK_COMPLETED, "Task Completed"),
            (EventType.TASK_CLOSED, "Task Closed"),
            (EventType.TASK_COMMENT_CREATED, "Task Comment Created"),
            (EventType.TASK_COMMENT_UPDATED, "Task Comment Updated"),
            (EventType.TASK_COMMENT_DELETED, "Task Comment Deleted"),
            (EventType.TASK_LABELS_ADJUSTED, "Task Labels Adjusted"),
            (EventType.TASK_METADATA_CREATED, "Task Metadata Created"),
            (EventType.TASK_METADATA_UPDATED, "Task Metadata Updated"),
        ],
    },
    {
        "key": "staff",
        "label": "Staff",
        "events": [
            (EventType.STAFF_CREATED, "Staff Created"),
            (EventType.STAFF_UPDATED, "Staff Updated"),
            (EventType.STAFF_ACTIVATED, "Staff Activated"),
            (EventType.STAFF_DEACTIVATED, "Staff Deactivated"),
            (EventType.STAFF_EXTERNAL_IDENTIFIER_CREATED, "Staff External Identifier Created"),
            (EventType.STAFF_EXTERNAL_IDENTIFIER_UPDATED, "Staff External Identifier Updated"),
            (EventType.STAFF_EXTERNAL_IDENTIFIER_DELETED, "Staff External Identifier Deleted"),
            (EventType.STAFF_METADATA_CREATED, "Staff Metadata Created"),
            (EventType.STAFF_METADATA_UPDATED, "Staff Metadata Updated"),
            (EventType.STAFF_METADATA_DELETED, "Staff Metadata Deleted"),
        ],
    },
    {
        "key": "documents",
        "label": "Documents",
        "events": [
            (EventType.DOCUMENT_RECEIVED, "Document Received"),
            (EventType.DOCUMENT_LINKED_TO_PATIENT, "Document Linked to Patient"),
            (EventType.DOCUMENT_CATEGORIZED, "Document Categorized"),
            (EventType.DOCUMENT_REVIEWED, "Document Reviewed"),
            (EventType.DOCUMENT_DELETED, "Document Deleted"),
            (EventType.DOCUMENT_DELEGATED, "Document Delegated"),
            (EventType.DOCUMENT_FIELDS_UPDATED, "Document Fields Updated"),
            (EventType.DOCUMENT_REVIEWER_ASSIGNED, "Document Reviewer Assigned"),
            (EventType.DOCUMENT_REFERENCE_CREATED, "Document Reference Created"),
            (EventType.DOCUMENT_REFERENCE_UPDATED, "Document Reference Updated"),
            (EventType.DOCUMENT_REFERENCE_DELETED, "Document Reference Deleted"),
        ],
    },
    {
        "key": "messages",
        "label": "Messages & Letters",
        "events": [
            (EventType.MESSAGE_CREATED, "Message Created"),
            (EventType.MESSAGE_TRANSMISSION_CREATED, "Message Transmission Created"),
            (EventType.MESSAGE_TRANSMISSION_UPDATED, "Message Transmission Updated"),
            (EventType.LETTER_CREATED, "Letter Created"),
            (EventType.LETTER_UPDATED, "Letter Updated"),
            (EventType.LETTER_ACTION_EVENT_CREATED, "Letter Action Created"),
            (EventType.LETTER_ACTION_EVENT_UPDATED, "Letter Action Updated"),
        ],
    },
    {
        "key": "care_teams",
        "label": "Care Teams & Groups",
        "events": [
            (EventType.CARE_TEAM_MEMBERSHIP_CREATED, "Care Team Membership Created"),
            (EventType.CARE_TEAM_MEMBERSHIP_UPDATED, "Care Team Membership Updated"),
            (EventType.CARE_TEAM_MEMBERSHIP_DELETED, "Care Team Membership Deleted"),
            (EventType.PATIENT_GROUP_CREATED, "Patient Group Created"),
            (EventType.PATIENT_GROUP_UPDATED, "Patient Group Updated"),
            (EventType.PATIENT_GROUP_MEMBERSHIP_CREATED, "Patient Group Membership Created"),
            (EventType.PATIENT_GROUP_MEMBERSHIP_UPDATED, "Patient Group Membership Updated"),
            (EventType.PATIENT_GROUP_MEMBERSHIP_DELETED, "Patient Group Membership Deleted"),
        ],
    },
    {
        "key": "billing",
        "label": "Billing, Coverage & Consent",
        "events": [
            (EventType.BILLING_LINE_ITEM_CREATED, "Billing Line Item Created"),
            (EventType.BILLING_LINE_ITEM_UPDATED, "Billing Line Item Updated"),
            (EventType.CLAIM_CREATED, "Claim Created"),
            (EventType.CLAIM_UPDATED, "Claim Updated"),
            (EventType.CLAIM_INCIDENT_TO_CHANGED, "Claim Incident-To Changed"),
            (EventType.CLAIM_QUEUE_MOVED, "Claim Queue Moved"),
            (EventType.CLAIM_SUPERVISING_PROVIDER_CHANGED, "Claim Supervising Provider Changed"),
            (EventType.COVERAGE_CREATED, "Coverage Created"),
            (EventType.COVERAGE_UPDATED, "Coverage Updated"),
            (EventType.COVERAGE_ELIGIBILITY_RESPONSE_CREATED, "Coverage Eligibility Response Created"),
            (EventType.COVERAGE_ELIGIBILITY_RESPONSE_UPDATED, "Coverage Eligibility Response Updated"),
            (EventType.COVERAGE_ELIGIBILITY_RESPONSE_ACTIVE, "Coverage Eligibility Response Active"),
            (EventType.COVERAGE_ELIGIBILITY_RESPONSE_FAILED, "Coverage Eligibility Response Failed"),
            (EventType.COVERAGE_ELIGIBILITY_RESPONSE_INACTIVE, "Coverage Eligibility Response Inactive"),
            (EventType.CONSENT_CREATED, "Consent Created"),
            (EventType.CONSENT_UPDATED, "Consent Updated"),
            (EventType.CONSENT_DELETED, "Consent Deleted"),
        ],
    },
]


# Events that are not about a specific patient. Everything else in the catalog
# is treated as patient-related and MUST include a top-level patient_id.
_NON_PATIENT_EVENTS: frozenset[str] = frozenset(
    {
        _n(EventType.STAFF_CREATED),
        _n(EventType.STAFF_UPDATED),
        _n(EventType.STAFF_ACTIVATED),
        _n(EventType.STAFF_DEACTIVATED),
        _n(EventType.STAFF_EXTERNAL_IDENTIFIER_CREATED),
        _n(EventType.STAFF_EXTERNAL_IDENTIFIER_UPDATED),
        _n(EventType.STAFF_EXTERNAL_IDENTIFIER_DELETED),
        _n(EventType.STAFF_METADATA_CREATED),
        _n(EventType.STAFF_METADATA_UPDATED),
        _n(EventType.STAFF_METADATA_DELETED),
        _n(EventType.PATIENT_GROUP_CREATED),
        _n(EventType.PATIENT_GROUP_UPDATED),
        _n(EventType.COMPOUND_MEDICATION_CREATED),
        _n(EventType.COMPOUND_MEDICATION_UPDATED),
    }
)


def all_event_names() -> list[str]:
    """Return every catalogued event name, in display order."""
    names: list[str] = []
    for category in CATEGORIES:
        for event_type, _label in category["events"]:
            names.append(_n(event_type))
    return names


def event_type_names(category_key: str) -> list[str]:
    """Return EventType.Name strings for a category (used as RESPONDS_TO)."""
    for category in CATEGORIES:
        if category["key"] == category_key:
            return [_n(event_type) for event_type, _label in category["events"]]
    raise KeyError(f"Unknown event category: {category_key}")


def is_patient_related(event_name: str) -> bool:
    """True when the event is about a patient and must carry patient_id."""
    return event_name not in _NON_PATIENT_EVENTS and event_name in _ALL_EVENT_NAMES_SET


def known_event(event_name: str) -> bool:
    return event_name in _ALL_EVENT_NAMES_SET


def event_label(event_name: str) -> str:
    """Human-readable label for a catalogued event name."""
    return _EVENT_LABELS.get(event_name) or event_name.replace("_", " ").title()


def catalog_for_ui() -> list[dict]:
    """JSON-serialisable catalog: categories with name/label pairs."""
    out: list[dict] = []
    for category in CATEGORIES:
        out.append(
            {
                "key": category["key"],
                "label": category["label"],
                "events": [
                    {"name": _n(event_type), "label": label}
                    for event_type, label in category["events"]
                ],
            }
        )
    return out


_ALL_EVENT_NAMES_SET: frozenset[str] = frozenset(all_event_names())
_EVENT_LABELS: dict[str, str] = {
    _n(event_type): label
    for category in CATEGORIES
    for event_type, label in category["events"]
}
PATIENT_RELATED: frozenset[str] = frozenset(
    name for name in _ALL_EVENT_NAMES_SET if name not in _NON_PATIENT_EVENTS
)
