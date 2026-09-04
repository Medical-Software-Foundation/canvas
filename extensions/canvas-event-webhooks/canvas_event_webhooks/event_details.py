"""
Optional rich event details for outbound webhooks.

Off by default (``include_details=False``). When enabled, the payload gains:

  - ``description`` — a human-readable sentence
  - ``actor`` — who performed the action (staff or patient name)
  - ``patient`` — patient name, MRN, and demographics
  - ``data`` — major fields from the event target (times, status, title, …)

Lookups are best-effort. Failures never block delivery. Names, MRNs, and
record fields are PHI — only send them to HIPAA-covered endpoints.

Intentionally omitted even when details are on: SSN, note body, message
content, document URLs, payment amounts, tax IDs, and similar sensitive
blobs.
"""

from __future__ import annotations

from logger import log

from canvas_event_webhooks.events_catalog import event_label

# Best-effort lookups must not block webhook delivery. Catch only expected
# attribute/type failures from optional Canvas models — never bare Exception.
_SAFE_ERRORS = (AttributeError, TypeError, ValueError)


def _is_safe_lookup_error(exc: BaseException) -> bool:
    if isinstance(exc, _SAFE_ERRORS):
        return True
    # Django RelatedObjectDoesNotExist / Model.DoesNotExist — do not import django
    # (blocked in the Canvas sandbox).
    return getattr(exc.__class__, "__name__", "").endswith("DoesNotExist")

_MOCK_TYPES = frozenset(
    {"Mock", "MagicMock", "NonCallableMock", "NonCallableMagicMock", "AsyncMock"}
)

_SHORT = 240


def enrich_event(event, event_name: str, patient_id: str | None) -> dict:
    """Return extra payload keys, or a minimal description if lookup fails."""
    try:
        instance = _target_instance(event)
        actor = _load_actor(event)
        patient = _load_patient(patient_id, instance)
        data = _extract_data(instance)
        extra: dict = {
            "description": _description(event_name, actor, patient, data),
        }
        if actor:
            extra["actor"] = actor
        if patient:
            extra["patient"] = patient
        if data:
            extra["data"] = data
        return extra
    except Exception as exc:
        if not _is_safe_lookup_error(exc):
            raise
        log.warning(
            "[Webhooks] Failed to attach event details (%s).",
            exc.__class__.__name__,
        )
        return {"description": event_label(event_name)}


def _is_mock(obj) -> bool:
    if obj is None:
        return True
    cls = getattr(obj, "__class__", None)
    name = getattr(cls, "__name__", "") if cls is not None else ""
    return name in _MOCK_TYPES


def _class_name(obj) -> str:
    if obj is None or _is_mock(obj):
        return ""
    cls = getattr(obj, "__class__", None)
    name = getattr(cls, "__name__", "") if cls is not None else ""
    if name in _MOCK_TYPES:
        return ""
    return name or ""


def _plain(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            text = iso()
            if text:
                return text
        except _SAFE_ERRORS:
            pass
    try:
        text = str(value).strip()
    except _SAFE_ERRORS:
        return None
    if not text or text.startswith("<Mock"):
        return None
    return text


def _short(value):
    text = _plain(value)
    if not isinstance(text, str):
        return text
    if len(text) > _SHORT:
        return text[: _SHORT - 1] + "…"
    return text


def _compact(data: dict) -> dict:
    out: dict = {}
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        out[key] = value
    return out


def _target_instance(event):
    try:
        target = getattr(event, "target", None)
        instance = getattr(target, "instance", None) if target is not None else None
    except _SAFE_ERRORS:
        return None
    if _is_mock(instance):
        return None
    return instance


def person_summary(obj, role: str | None = None) -> dict | None:
    """Staff or patient name block. Returns None when names cannot be read."""
    if obj is None or _is_mock(obj):
        return None
    first = _plain(getattr(obj, "first_name", None))
    middle = _plain(getattr(obj, "middle_name", None))
    last = _plain(getattr(obj, "last_name", None))
    prefix = _plain(getattr(obj, "prefix", None))
    full = _plain(getattr(obj, "full_name", None))
    if not full:
        parts = [p for p in (prefix, first, middle, last) if p]
        full = " ".join(parts) or None
    if not first and not last and not full:
        return None

    record_id = _plain(getattr(obj, "id", None))
    cls = _class_name(obj)
    resolved = role
    if cls == "Patient":
        resolved = "patient"
    elif cls == "Staff":
        resolved = "staff"

    out: dict = {
        "id": record_id,
        "first_name": first,
        "last_name": last,
        "full_name": full,
    }
    if resolved:
        out["type"] = resolved
    if prefix:
        out["prefix"] = prefix
    if resolved == "staff":
        npi = _plain(getattr(obj, "npi_number", None))
        if npi:
            out["npi"] = npi
        credentialed = _plain(getattr(obj, "credentialed_name", None))
        if credentialed:
            out["credentialed_name"] = credentialed
    if resolved == "patient":
        mrn = _plain(getattr(obj, "mrn", None))
        if mrn:
            out["mrn"] = mrn
        birth_date = _plain(getattr(obj, "birth_date", None))
        if birth_date:
            out["birth_date"] = birth_date
        sex = _plain(getattr(obj, "sex_at_birth", None))
        if sex:
            out["sex_at_birth"] = sex
    return _compact(out) or None


def _load_actor(event) -> dict | None:
    try:
        actor = getattr(event, "actor", None)
        user = getattr(actor, "instance", None) if actor is not None else None
    except _SAFE_ERRORS:
        return None
    if user is None or _is_mock(user):
        return None

    person = None
    try:
        person = getattr(user, "person_subclass", None)
    except _SAFE_ERRORS:
        person = None
    if person is None or _is_mock(person):
        try:
            if getattr(user, "is_staff", False):
                person = getattr(user, "staff", None)
            else:
                person = getattr(user, "patient", None)
        except _SAFE_ERRORS:
            person = None
    if person is None or _is_mock(person):
        person = user if _plain(getattr(user, "first_name", None)) else None
    if person is None:
        return None

    role = "staff"
    try:
        if getattr(user, "is_staff", None) is False:
            role = "patient"
    except _SAFE_ERRORS:
        pass
    cls = _class_name(person)
    if cls == "Patient":
        role = "patient"
    elif cls == "Staff":
        role = "staff"
    return person_summary(person, role=role)


def _load_patient(patient_id: str | None, instance) -> dict | None:
    if instance is not None:
        if _class_name(instance) == "Patient":
            summary = person_summary(instance, role="patient")
            if summary:
                return summary
        related = None
        try:
            related = getattr(instance, "patient", None)
        except _SAFE_ERRORS:
            related = None
        summary = person_summary(related, role="patient")
        if summary:
            return summary

    if not patient_id:
        return None
    try:
        from canvas_sdk.v1.data.patient import Patient

        found = Patient.objects.filter(id=patient_id).first()
    except _SAFE_ERRORS:
        found = None
    return person_summary(found, role="patient")


def _location_name(location) -> str | None:
    if location is None or _is_mock(location):
        return None
    for attr in ("full_name", "long_name", "name", "short_name"):
        value = _plain(getattr(location, attr, None))
        if value:
            return value
    return None


def _related_name(obj) -> str | None:
    if obj is None or _is_mock(obj):
        return None
    for attr in ("name", "title", "display", "label"):
        value = _plain(getattr(obj, attr, None))
        if value:
            return value
    return None


def _codings(instance) -> list[str] | None:
    try:
        related = getattr(instance, "codings", None)
        if related is None:
            return None
        rows = related.all()[:5]
    except _SAFE_ERRORS:
        return None
    displays: list[str] = []
    for row in rows:
        display = _plain(
            getattr(row, "display", None)
            or getattr(row, "name", None)
            or getattr(row, "code", None)
        )
        if display:
            displays.append(display)
    return displays or None


def _from_appointment(instance) -> dict:
    provider = person_summary(getattr(instance, "provider", None), role="staff")
    note_type = getattr(instance, "note_type", None)
    return {
        "record_type": "appointment",
        "start_time": _plain(getattr(instance, "start_time", None)),
        "duration_minutes": _plain(getattr(instance, "duration_minutes", None)),
        "status": _plain(getattr(instance, "status", None)),
        "description": _short(getattr(instance, "description", None)),
        "comment": _short(getattr(instance, "comment", None)),
        "meeting_link": _plain(getattr(instance, "meeting_link", None)),
        "provider": provider,
        "location": _location_name(getattr(instance, "location", None)),
        "note_type": _related_name(note_type) if not isinstance(note_type, str) else _plain(note_type),
    }


def _from_task(instance) -> dict:
    return {
        "record_type": "task",
        "title": _short(getattr(instance, "title", None)),
        "status": _plain(getattr(instance, "status", None)),
        "priority": _plain(getattr(instance, "priority", None)),
        "due": _plain(getattr(instance, "due", None)),
        "task_type": _plain(getattr(instance, "task_type", None)),
        "tag": _plain(getattr(instance, "tag", None)),
        "assignee": person_summary(getattr(instance, "assignee", None), role="staff"),
        "creator": person_summary(getattr(instance, "creator", None), role="staff"),
    }


def _from_note(instance) -> dict:
    return {
        "record_type": "note",
        "title": _short(getattr(instance, "title", None)),
        "note_type": _plain(getattr(instance, "note_type", None)),
        "datetime_of_service": _plain(getattr(instance, "datetime_of_service", None)),
        "place_of_service": _plain(getattr(instance, "place_of_service", None)),
        "provider": person_summary(getattr(instance, "provider", None), role="staff"),
        "supervising_provider": person_summary(
            getattr(instance, "supervising_provider", None), role="staff"
        ),
        "location": _location_name(getattr(instance, "location", None)),
    }


def _from_prescription(instance) -> dict:
    medication = getattr(instance, "medication", None)
    med_name = None
    if medication is not None and not _is_mock(medication):
        codes = _codings(medication)
        med_name = (codes or [None])[0] or _plain(
            getattr(medication, "clinical_quantity_description", None)
        )
    return {
        "record_type": "prescription",
        "status": _plain(getattr(instance, "status", None)),
        "medication": med_name,
        "sig": _short(getattr(instance, "sig_original_input", None)),
        "dose_quantity": _plain(getattr(instance, "dose_quantity", None)),
        "dose_form": _plain(getattr(instance, "dose_form", None)),
        "dose_route": _plain(getattr(instance, "dose_route", None)),
        "dose_frequency": _plain(getattr(instance, "dose_frequency", None)),
        "dispense_quantity": _plain(getattr(instance, "dispense_quantity", None)),
        "count_of_refills_allowed": _plain(getattr(instance, "count_of_refills_allowed", None)),
        "pharmacy_name": _plain(getattr(instance, "pharmacy_name", None)),
        "written_date": _plain(getattr(instance, "written_date", None)),
        "prescriber": person_summary(getattr(instance, "prescriber", None), role="staff"),
        "is_refill": _plain(getattr(instance, "is_refill", None)),
        "error_message": _short(getattr(instance, "error_message", None)),
    }


def _from_medication(instance) -> dict:
    return {
        "record_type": "medication",
        "status": _plain(getattr(instance, "status", None)),
        "codings": _codings(instance),
        "clinical_quantity_description": _short(
            getattr(instance, "clinical_quantity_description", None)
        ),
        "national_drug_code": _plain(getattr(instance, "national_drug_code", None)),
        "start_date": _plain(getattr(instance, "start_date", None)),
        "end_date": _plain(getattr(instance, "end_date", None)),
    }


def _from_lab_order(instance) -> dict:
    tests: list[str] = []
    try:
        for test in instance.tests.all()[:8]:
            name = _plain(getattr(test, "ontology_test_name", None))
            if name:
                tests.append(name)
    except _SAFE_ERRORS:
        tests = []
    return {
        "record_type": "lab_order",
        "date_ordered": _plain(getattr(instance, "date_ordered", None)),
        "requisition_number": _plain(getattr(instance, "requisition_number", None)),
        "lab_partner": _plain(getattr(instance, "ontology_lab_partner", None)),
        "comment": _short(getattr(instance, "comment", None)),
        "manual_processing_status": _plain(getattr(instance, "manual_processing_status", None)),
        "ordering_provider": person_summary(
            getattr(instance, "ordering_provider", None), role="staff"
        ),
        "tests": tests,
    }


def _from_lab_report(instance) -> dict:
    return {
        "record_type": "lab_report",
        "custom_document_name": _short(getattr(instance, "custom_document_name", None)),
        "requisition_number": _plain(getattr(instance, "requisition_number", None)),
        "date_performed": _plain(getattr(instance, "date_performed", None)),
        "original_date": _plain(getattr(instance, "original_date", None)),
        "transmission_type": _plain(getattr(instance, "transmission_type", None)),
        "external_id": _plain(getattr(instance, "external_id", None)),
    }


def _from_imaging_order(instance) -> dict:
    return {
        "record_type": "imaging_order",
        "imaging": _short(getattr(instance, "imaging", None)),
        "status": _plain(getattr(instance, "status", None)),
        "priority": _plain(getattr(instance, "priority", None)),
        "date_time_ordered": _plain(getattr(instance, "date_time_ordered", None)),
        "ordering_provider": person_summary(
            getattr(instance, "ordering_provider", None), role="staff"
        ),
    }


def _from_imaging_report(instance) -> dict:
    return {
        "record_type": "imaging_report",
        "name": _short(
            getattr(instance, "name", None) or getattr(instance, "custom_document_name", None)
        ),
        "status": _plain(getattr(instance, "status", None)),
        "original_date": _plain(getattr(instance, "original_date", None)),
    }


def _from_condition(instance) -> dict:
    return {
        "record_type": "condition",
        "clinical_status": _plain(getattr(instance, "clinical_status", None)),
        "onset_date": _plain(getattr(instance, "onset_date", None)),
        "resolution_date": _plain(getattr(instance, "resolution_date", None)),
        "codings": _codings(instance),
        "surgical": _plain(getattr(instance, "surgical", None)),
    }


def _from_allergy(instance) -> dict:
    return {
        "record_type": "allergy",
        "status": _plain(getattr(instance, "status", None)),
        "severity": _plain(getattr(instance, "severity", None)),
        "category": _plain(getattr(instance, "category", None)),
        "onset_date": _plain(getattr(instance, "onset_date", None)),
        "codings": _codings(instance),
    }


def _from_patient(instance) -> dict:
    summary = person_summary(instance, role="patient") or {}
    data = dict(summary)
    data["record_type"] = "patient"
    data["active"] = _plain(getattr(instance, "active", None))
    data["nickname"] = _plain(getattr(instance, "nickname", None))
    return data


def _from_staff(instance) -> dict:
    summary = person_summary(instance, role="staff") or {}
    data = dict(summary)
    data["record_type"] = "staff"
    data["active"] = _plain(getattr(instance, "active", None))
    return data


def _from_message(instance) -> dict:
    # Message body is clinical correspondence — omit it.
    return {
        "record_type": "message",
        "read": _plain(getattr(instance, "read", None)),
        "sender": person_summary(getattr(instance, "sender", None))
        or person_summary(getattr(getattr(instance, "sender", None), "person_subclass", None)),
        "recipient": person_summary(getattr(instance, "recipient", None))
        or person_summary(getattr(getattr(instance, "recipient", None), "person_subclass", None)),
    }


def _from_letter(instance) -> dict:
    return {
        "record_type": "letter",
        "printed": _plain(getattr(instance, "printed", None)),
        "staff": person_summary(getattr(instance, "staff", None), role="staff"),
    }


def _from_care_team(instance) -> dict:
    role = getattr(instance, "role", None)
    return {
        "record_type": "care_team_membership",
        "status": _plain(getattr(instance, "status", None)),
        "staff": person_summary(getattr(instance, "staff", None), role="staff"),
        "role": _related_name(role) or _plain(getattr(role, "display", None)),
    }


def _from_claim(instance) -> dict:
    return {
        "record_type": "claim",
        "current_queue": _plain(
            getattr(instance, "current_queue", None) or getattr(instance, "queue", None)
        ),
        "note_id": _plain(getattr(getattr(instance, "note", None), "id", None)),
    }


def _from_coverage(instance) -> dict:
    transactor = getattr(instance, "transactor", None)
    payer = _related_name(transactor) if transactor is not None else None
    return {
        "record_type": "coverage",
        "state": _plain(getattr(instance, "state", None)),
        "coverage_type": _plain(getattr(instance, "coverage_type", None) or getattr(instance, "type", None)),
        "rank": _plain(getattr(instance, "rank", None)),
        "payer": payer,
    }


def _from_document(instance) -> dict:
    return {
        "record_type": "document",
        "status": _plain(getattr(instance, "status", None)),
        "document_content_type": _plain(getattr(instance, "document_content_type", None)),
        "business_identifier": _plain(getattr(instance, "business_identifier", None)),
    }


def _generic(instance) -> dict:
    note_type = getattr(instance, "note_type", None)
    return {
        "record_type": _class_name(instance) or None,
        "title": _short(getattr(instance, "title", None)),
        "name": _short(getattr(instance, "name", None)),
        "status": _plain(getattr(instance, "status", None)),
        "state": _plain(getattr(instance, "state", None)),
        "description": _short(getattr(instance, "description", None)),
        "codings": _codings(instance),
        "note_type": _plain(note_type) if isinstance(note_type, str) else _related_name(note_type),
        "provider": person_summary(getattr(instance, "provider", None), role="staff"),
    }


_BY_CLASS = {
    "Appointment": _from_appointment,
    "Task": _from_task,
    "Note": _from_note,
    "Prescription": _from_prescription,
    "Medication": _from_medication,
    "LabOrder": _from_lab_order,
    "LabReport": _from_lab_report,
    "ImagingOrder": _from_imaging_order,
    "ImagingReport": _from_imaging_report,
    "ReferralReport": _from_imaging_report,
    "Condition": _from_condition,
    "AllergyIntolerance": _from_allergy,
    "Patient": _from_patient,
    "Staff": _from_staff,
    "Message": _from_message,
    "Letter": _from_letter,
    "CareTeamMembership": _from_care_team,
    "Claim": _from_claim,
    "Coverage": _from_coverage,
    "DocumentReference": _from_document,
}


def _extract_data(instance) -> dict | None:
    if instance is None or _is_mock(instance):
        return None
    handler = _BY_CLASS.get(_class_name(instance), _generic)
    try:
        data = handler(instance)
    except _SAFE_ERRORS:
        data = _generic(instance)
    packed = _compact(data)
    return packed or None


def _name_of(block: dict | None) -> str | None:
    if not block:
        return None
    return block.get("full_name") or None


def _description(event_name: str, actor: dict | None, patient: dict | None, data: dict | None) -> str:
    label = event_label(event_name)
    actor_name = _name_of(actor) or "Canvas"
    patient_name = _name_of(patient)

    if patient_name:
        sentence = f"{actor_name} — {label} for patient {patient_name}"
    else:
        sentence = f"{actor_name} — {label}"

    extras: list[str] = []
    data = data or {}
    title = data.get("title") or data.get("name") or data.get("medication") or data.get("imaging")
    if title:
        extras.append(f'"{title}"')
    if data.get("start_time"):
        extras.append(f"at {data['start_time']}")
    elif data.get("datetime_of_service"):
        extras.append(f"at {data['datetime_of_service']}")
    elif data.get("date_ordered"):
        extras.append(f"ordered {data['date_ordered']}")
    elif data.get("due"):
        extras.append(f"due {data['due']}")
    status = data.get("status") or data.get("clinical_status") or data.get("state")
    if status:
        extras.append(f"status {status}")
    provider = data.get("provider") or data.get("prescriber") or data.get("ordering_provider")
    if isinstance(provider, dict) and provider.get("full_name"):
        extras.append(f"provider {provider['full_name']}")
    if data.get("location"):
        extras.append(f"at {data['location']}")
    if data.get("pharmacy_name"):
        extras.append(f"pharmacy {data['pharmacy_name']}")
    assignee = data.get("assignee")
    if isinstance(assignee, dict) and assignee.get("full_name"):
        extras.append(f"assigned to {assignee['full_name']}")
    if extras:
        sentence = f"{sentence} ({', '.join(extras)})"
    return sentence + "."
