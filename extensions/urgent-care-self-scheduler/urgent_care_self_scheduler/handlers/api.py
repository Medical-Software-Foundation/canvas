import datetime
import json
import uuid
from http import HTTPStatus
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import Appointment as AppointmentEffect
from canvas_sdk.effects.note.base import AppointmentIdentifier
from canvas_sdk.effects.patient_metadata import PatientMetadata
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPIRoute
from logger import log

# `_APPOINTMENT_QUERY_BUFFER` and `_NON_BLOCKING_APPOINTMENT_STATUSES` are shared from
# slot_search (one source of truth) so the duplicate-visit query here and the
# slot-blocking query there can't drift apart — the statuses that don't block a slot
# are exactly those that don't count as the patient already having an upcoming visit.
from urgent_care_self_scheduler.slot_search import (
    _APPOINTMENT_QUERY_BUFFER,
    _NON_BLOCKING_APPOINTMENT_STATUSES,
    find_available_slots,
    resolve_urgent_care_note_type,
)

DEFAULT_LEAD_TIME_MINUTES = 30
SLOT_WINDOW_DAYS = 3
EXTERNAL_ID_SYSTEM = "urgent-care-self-scheduler"
PENDING_RFV_KEY_PREFIX = "pending_rfv_"
RFV_MAX_CHARS = 500


def _patient_has_upcoming_urgent_care_visit(
    patient_id: str,
    *,
    note_type: Any,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> bool:
    """True if the patient already has a (non-cancelled) urgent-care visit in the window.

    Urgent-care visits are appointments of the configured urgent-care NoteType
    (`Appointment.note_type`). Used to block a patient from self-booking a second
    urgent-care visit on any day while one is already upcoming.
    """
    from canvas_sdk.v1.data.appointment import Appointment

    return bool(
        Appointment.objects.filter(
            patient__id=patient_id,
            note_type=note_type,
            start_time__gte=window_start - _APPOINTMENT_QUERY_BUFFER,
            start_time__lt=window_end + _APPOINTMENT_QUERY_BUFFER,
        )
        .exclude(status__in=_NON_BLOCKING_APPOINTMENT_STATUSES)
        .exists()
    )


def _first_coding_display(record: Any) -> str | None:
    """Returns the first coding's display string, using the prefetch cache.

    Uses `list(record.codings.all())[0]` rather than `.first()` so callers
    using `prefetch_related('codings')` actually hit the cache; `.first()`
    can re-query even when codings are prefetched.
    """
    if not hasattr(record, "codings"):
        # Record type doesn't expose a `codings` relation.
        return None
    codings = list(record.codings.all())
    if codings and getattr(codings[0], "display", None):
        return str(codings[0].display)
    return None


def _medication_label(medication: Any) -> str:
    return _first_coding_display(medication) or "Unknown medication"


def _allergy_label(allergy: Any) -> str:
    # Prefer the structured coding display — that's the actual allergen.
    # `narrative` is free-text and is sometimes only the *reaction* (e.g., "rash"),
    # which doesn't tell the patient what they're allergic to.
    coding_display = _first_coding_display(allergy)
    if coding_display:
        return coding_display
    narrative = getattr(allergy, "narrative", "") or ""
    if narrative:
        return str(narrative)
    return "Unknown allergy"


def _format_medications(medications: Iterable[Any]) -> list[dict]:
    return [{"id": str(m.id), "label": _medication_label(m)} for m in medications]


def _format_allergies(allergies: Iterable[Any]) -> list[dict]:
    return [{"id": str(a.id), "label": _allergy_label(a)} for a in allergies]


def _patient_review(patient_id: str) -> dict | None:
    """Returns the active medication + allergy review payload for `patient_id`.

    Returns None if the patient cannot be found.
    """
    from canvas_sdk.v1.data.allergy_intolerance import AllergyIntolerance
    from canvas_sdk.v1.data.medication import Medication
    from canvas_sdk.v1.data.patient import Patient

    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        return None

    medications = (
        Medication.objects.filter(patient=patient, deleted=False)
        .exclude(entered_in_error__isnull=False)
        .active()
        .prefetch_related("codings")
    )
    allergies = (
        AllergyIntolerance.objects.filter(patient=patient, deleted=False, status="active")
        .exclude(entered_in_error__isnull=False)
        .committed()
        .prefetch_related("codings")
    )
    return {
        "medications": _format_medications(medications),
        "allergies": _format_allergies(allergies),
    }


def _resolve_modality(value: Any) -> str:
    """Normalizes the URGENT_CARE_VISIT_MODALITY secret to 'telehealth' | 'in_person'.

    Defaults to 'telehealth' when unset. Drives the patient-facing slot labels and
    success-pane copy; the appointment's actual video-vs-in-person nature is
    determined by the configured NoteType, and for a telehealth NoteType Canvas
    generates and delivers the join link via the portal Appointments tab.
    """
    normalized = (str(value).strip().lower() if value is not None else "")
    if normalized in ("", "telehealth", "in_person"):
        return "in_person" if normalized == "in_person" else "telehealth"
    # A non-empty value we don't recognize (e.g. the hyphenated "in-person") is a
    # likely misconfiguration — log it (we still default to telehealth) rather than
    # swapping modality without a trace.
    log.warning(
        f"_resolve_modality: unrecognized URGENT_CARE_VISIT_MODALITY {value!r}; "
        "defaulting to 'telehealth' (expected 'telehealth' or 'in_person')"
    )
    return "telehealth"


def _parse_lead_time(value: Any) -> int:
    if value is None:
        return DEFAULT_LEAD_TIME_MINUTES
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_LEAD_TIME_MINUTES
    return n if n >= 0 else DEFAULT_LEAD_TIME_MINUTES


def _resolve_timezone(tz_string: str | None) -> ZoneInfo:
    if not tz_string:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_string)
    except (KeyError, ValueError):
        # Unknown timezone key (ZoneInfoNotFoundError subclasses KeyError) or a
        # malformed value in the practice-location setting. NB: catch KeyError
        # rather than importing ZoneInfoNotFoundError — the Canvas plugin-runner
        # sandbox only allowlists `ZoneInfo` from the zoneinfo module.
        return ZoneInfo("UTC")


def _active_location() -> tuple[str | None, ZoneInfo]:
    """Returns (active practice location id, its timezone) in a single lookup.

    Returns (None, UTC) when there is no active location. Callers needing both
    values (e.g. booking) use this to avoid querying PracticeLocation twice.
    """
    from canvas_sdk.v1.data.practicelocation import PracticeLocation, PracticeLocationSetting

    location = PracticeLocation.objects.filter(active=True).first()
    if not location:
        return None, ZoneInfo("UTC")
    setting = PracticeLocationSetting.objects.filter(
        practice_location=location, name="last_known_timezone"
    ).first()
    return str(location.id), _resolve_timezone(setting.value if setting else None)


def _practice_timezone() -> ZoneInfo:
    """Returns the timezone of the active practice location, or UTC if unset.

    Used only as a fallback for the slot search: each clinic calendar carries its
    own `Calendar.timezone`, which is authoritative. This default applies only if a
    calendar's timezone somehow fails to resolve.
    """
    return _active_location()[1]


def _location_index() -> dict[str, tuple[str, str]]:
    """Maps each active PracticeLocation's `full_name` to `(id, display_name)`.

    Clinic calendars are titled ``"{Provider}: Clinic: {Location full_name}"``, so
    this lets the slot search resolve which location a slot belongs to and book the
    appointment there (and label the slot for in-person modality). `display_name`
    prefers `short_name` for a compact wizard label, falling back to `full_name`.
    """
    from canvas_sdk.v1.data.practicelocation import PracticeLocation

    # Build by accumulating (NOT a dict comprehension) so we can detect and drop
    # locations that share a full_name — a calendar's title suffix can't pick
    # between them, and silently keeping one would book at the wrong site. Mirrors
    # the ambiguous-Staff.full_name handling in slot_search.
    index: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for location in PracticeLocation.objects.filter(active=True):
        if location.full_name in index:
            ambiguous.add(location.full_name)
        index[location.full_name] = (str(location.id), location.short_name or location.full_name)
    for name in ambiguous:
        index.pop(name, None)
        log.error(
            f"_location_index: multiple active PracticeLocations share full_name {name!r}; "
            "dropping it so a calendar at that name books the default location, not the wrong site"
        )
    return index


class MeAPI(PatientSessionAuthMixin, SimpleAPIRoute):
    """Returns the logged-in patient's active medications + allergies for the wizard's review step."""

    PATH = "/api/me"

    def get(self) -> list[Response | Effect]:
        patient_id = self.request.headers.get("canvas-logged-in-user-id")
        if not patient_id:
            return [JSONResponse({"error": "no session"}, status_code=HTTPStatus.UNAUTHORIZED)]

        review = _patient_review(patient_id)
        if review is None:
            log.error(f"MeAPI: patient {patient_id} not found")
            return [JSONResponse({"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(review)]


class SlotsAPI(PatientSessionAuthMixin, SimpleAPIRoute):
    """Returns available urgent-care slots for the next few days."""

    PATH = "/api/slots"

    def get(self) -> list[Response | Effect]:
        secrets = getattr(self, "secrets", {}) or {}
        note_type_name = (secrets.get("URGENT_CARE_NOTE_TYPE_NAME") or "").strip()
        if not note_type_name:
            log.error("SlotsAPI: URGENT_CARE_NOTE_TYPE_NAME secret is not set")
            return [
                JSONResponse(
                    {"error": "scheduler unavailable"},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]

        patient_id = self.request.headers.get("canvas-logged-in-user-id")
        lead_time = _parse_lead_time(secrets.get("URGENT_CARE_LEAD_TIME_MINUTES"))
        fallback_phone = (secrets.get("URGENT_CARE_FALLBACK_PHONE") or "").strip()
        practice_tz = _practice_timezone()
        now = datetime.datetime.now(datetime.timezone.utc)
        window_end = now + datetime.timedelta(days=SLOT_WINDOW_DAYS)
        # Resolve the NoteType once and reuse it for both slot search and the
        # existing-visit check, rather than resolving twice.
        note_type = resolve_urgent_care_note_type(note_type_name)
        slots = find_available_slots(
            note_type_name=note_type_name,
            window_start=now,
            window_end=window_end,
            practice_timezone=practice_tz,
            now=now,
            lead_time_minutes=lead_time,
            note_type=note_type,
            location_index=_location_index(),
        )
        existing_urgent_care = False
        if patient_id and note_type is not None:
            existing_urgent_care = _patient_has_upcoming_urgent_care_visit(
                patient_id, note_type=note_type, window_start=now, window_end=window_end
            )
        return [
            JSONResponse(
                {
                    "slots": slots,
                    "fallback_phone": fallback_phone,
                    "existing_urgent_care_visit": existing_urgent_care,
                    # The wizard labels each slot with its location only for in-person
                    # visits (telehealth is virtual — location is irrelevant there).
                    "modality": _resolve_modality(secrets.get("URGENT_CARE_VISIT_MODALITY")),
                }
            )
        ]


def _validate_intake_payload(intake: Any) -> str | None:
    if not isinstance(intake, dict):
        return "intake must be an object"
    rfv = (intake.get("reason_for_visit") or "").strip()
    if not rfv:
        return "reason_for_visit is required"
    if len(rfv) > RFV_MAX_CHARS:
        return f"reason_for_visit exceeds {RFV_MAX_CHARS} characters"
    if not (intake.get("symptom_duration") or "").strip():
        return "symptom_duration is required"
    return None


def _build_task_title(patient_name: str, reason_for_visit: str) -> str:
    rfv_short = (reason_for_visit or "").strip().replace("\n", " ")
    if len(rfv_short) > 80:
        rfv_short = rfv_short[:77] + "..."
    return f"Urgent care intake — {patient_name}: {rfv_short}"


def _flagged_change_lines(intake: dict) -> list[str]:
    """Returns one line per medication/allergy change the patient flagged."""
    lines: list[str] = []
    for label_word, key in (("Medication", "medications"), ("Allergy", "allergies")):
        section = intake.get(key) or {}
        for change in section.get("changes") or []:
            item = (change.get("label") or "").strip() or f"(unknown {label_word.lower()})"
            note = (change.get("note") or "").strip()
            lines.append(f"{label_word}: {item}" + (f" — {note}" if note else ""))
    return lines


def _build_task_comment(intake: dict, change_lines: list[str] | None = None) -> str | None:
    """Builds the intake summary surfaced as a comment on the care-team task:
    symptom duration plus any flagged medication/allergy changes.

    The encounter note's HPI carries the same detail, but the care team triages
    from the task queue — so the duration and flagged changes are surfaced here
    too rather than left only on the note. Returns None if there's nothing to add.
    Pass `change_lines` to reuse an already-computed `_flagged_change_lines(intake)`.
    """
    lines: list[str] = []
    duration = (intake.get("symptom_duration") or "").strip()
    if duration:
        lines.append(f"Symptom duration: {duration}")
    if change_lines is None:
        change_lines = _flagged_change_lines(intake)
    if change_lines:
        lines.append("Patient flagged the following during intake:")
        lines.extend(f"• {line}" for line in change_lines)
    return "\n".join(lines) if lines else None


def _intake_to_metadata_value(intake: dict) -> str:
    return json.dumps(intake, separators=(",", ":"))


def _patient_full_name(patient_id: str) -> str:
    from canvas_sdk.v1.data.patient import Patient

    try:
        patient = Patient.objects.only("first_name", "last_name").get(id=patient_id)
    except Patient.DoesNotExist:
        return "patient"
    first = (patient.first_name or "").strip()
    last = (patient.last_name or "").strip()
    return f"{first} {last}".strip() or "patient"


class BookAPI(PatientSessionAuthMixin, SimpleAPIRoute):
    """POST /api/book — books the urgent-care visit, returning effects for the appointment + task + RFV stash."""

    PATH = "/api/book"

    def post(self) -> list[Response | Effect]:
        secrets = getattr(self, "secrets", {}) or {}
        note_type_name = (secrets.get("URGENT_CARE_NOTE_TYPE_NAME") or "").strip()
        if not note_type_name:
            return [
                JSONResponse(
                    {"error": "scheduler unavailable"},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]

        patient_id = self.request.headers.get("canvas-logged-in-user-id")
        if not patient_id:
            return [JSONResponse({"error": "no session"}, status_code=HTTPStatus.UNAUTHORIZED)]

        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            return [JSONResponse({"error": "invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        slot = body.get("slot") or {}
        intake = body.get("intake") or {}

        validation_error = _validate_intake_payload(intake)
        if validation_error:
            return [
                JSONResponse({"error": validation_error}, status_code=HTTPStatus.BAD_REQUEST)
            ]

        provider_id = (slot.get("provider_id") or "").strip()
        start_iso = (slot.get("start_iso") or "").strip()
        if not provider_id or not start_iso:
            return [
                JSONResponse(
                    {"error": "slot.provider_id and slot.start_iso are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Resolve the urgent-care NoteType once and reuse it for both the slot
        # re-validation and the appointment effect below.
        note_type = resolve_urgent_care_note_type(note_type_name)
        if note_type is None:
            return [
                JSONResponse(
                    {"error": "scheduler misconfigured"},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]
        duration_minutes = note_type.online_duration

        # Re-validate the slot is still on offer.
        lead_time = _parse_lead_time(secrets.get("URGENT_CARE_LEAD_TIME_MINUTES"))
        practice_location_id, practice_tz = _active_location()
        if not practice_location_id:
            # Guard up front: without an active location the timezone falls back to
            # UTC, so bail before computing any slots against the wrong zone.
            log.error("BookAPI: no active PracticeLocation found")
            return [
                JSONResponse(
                    {"error": "scheduler misconfigured"},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]
        now = datetime.datetime.now(datetime.timezone.utc)

        # Parse the requested slot up front so malformed input is rejected before
        # any slot computation.
        try:
            start_time = datetime.datetime.fromisoformat(start_iso)
        except ValueError:
            return [
                JSONResponse({"error": "invalid start_iso"}, status_code=HTTPStatus.BAD_REQUEST)
            ]

        available = find_available_slots(
            note_type_name=note_type_name,
            window_start=now,
            window_end=now + datetime.timedelta(days=SLOT_WINDOW_DAYS),
            practice_timezone=practice_tz,
            now=now,
            lead_time_minutes=lead_time,
            note_type=note_type,
            location_index=_location_index(),
        )
        # Match by absolute instant + provider, not by raw ISO string: slots from
        # different-timezone location calendars carry different UTC offsets, so the
        # same moment can be spelled more than one way.
        match = next(
            (
                s
                for s in available
                if s["provider_id"] == provider_id
                and datetime.datetime.fromisoformat(s["start_iso"]) == start_time
            ),
            None,
        )
        if match is None:
            return [
                JSONResponse({"error": "slot_taken"}, status_code=HTTPStatus.CONFLICT)
            ]

        # Book into the location the matched slot belongs to (resolved server-side,
        # not trusted from the request body). Falls back to the active location for
        # calendars with no location suffix (single-site practices).
        booking_location_id = match.get("location_id") or practice_location_id
        if not match.get("location_id") and match.get("location_unresolved"):
            # The slot's calendar HAD a location suffix we couldn't resolve — this
            # booking lands at the default location, which may not be the intended
            # site. Leave a book-time breadcrumb (the search-time error doesn't tie
            # to a specific booking); benign single-site calendars don't reach here.
            log.warning(
                f"BookAPI: booking provider {provider_id} at {start_iso} into the "
                f"default location {booking_location_id} — the slot's calendar "
                "location could not be resolved (check calendar title vs PracticeLocation)"
            )

        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=practice_tz)

        # Hard block: don't let a patient self-book a second urgent-care visit
        # while one is already upcoming in the window (any day). The wizard blocks
        # this in the UI; this enforces it server-side if the client is bypassed.
        if _patient_has_upcoming_urgent_care_visit(
            patient_id,
            note_type=note_type,
            window_start=now,
            window_end=now + datetime.timedelta(days=SLOT_WINDOW_DAYS),
        ):
            return [
                JSONResponse(
                    {"error": "already_has_urgent_care"}, status_code=HTTPStatus.CONFLICT
                )
            ]

        correlation_id = str(uuid.uuid4())

        from canvas_sdk.v1.data.appointment import AppointmentProgressStatus

        appointment = AppointmentEffect(
            appointment_note_type_id=str(note_type.id),
            patient_id=patient_id,
            start_time=start_time,
            duration_minutes=duration_minutes,
            practice_location_id=booking_location_id,
            provider_id=provider_id,
            status=AppointmentProgressStatus.CONFIRMED,
            external_identifiers=[
                AppointmentIdentifier(system=EXTERNAL_ID_SYSTEM, value=correlation_id)
            ],
        )

        patient_full_name = _patient_full_name(patient_id)
        task_team_id = (secrets.get("URGENT_CARE_TASK_TEAM_ID") or "").strip()
        flagged_lines = _flagged_change_lines(intake)
        has_flagged_changes = bool(flagged_lines)
        task_comment = _build_task_comment(intake, flagged_lines)
        task_title = _build_task_title(patient_full_name, intake.get("reason_for_visit", ""))
        if has_flagged_changes:
            # Flag at-a-glance in the queue; full detail goes in the task comment below.
            task_title += " — med/allergy changes flagged"
        task_id = str(uuid.uuid4())
        task_kwargs: dict[str, Any] = {
            "id": task_id,
            "title": task_title,
            "patient_id": patient_id,
            "due": start_time,
            "status": TaskStatus.OPEN,
            "labels": ["urgent-care-intake"] + ([] if task_team_id else ["unassigned"]),
        }
        if task_team_id:
            task_kwargs["team_id"] = task_team_id
        task = AddTask(**task_kwargs)

        # Stash the intake payload for the UrgentCareRfvOriginator handler, which
        # originates the RFV/HPI commands once the appointment's note exists.
        rfv_stash = PatientMetadata(
            patient_id=patient_id, key=f"{PENDING_RFV_KEY_PREFIX}{correlation_id}"
        )

        # Write the intake stash FIRST as a best-effort ordering so it tends to
        # commit before `appointment.create()` fires APPOINTMENT_CREATED. This is
        # NOT a hard guarantee — effect commit ordering isn't contractual — so the
        # real safety net is UrgentCareRfvOriginator, which also listens to
        # NOTE_STATE_CHANGE_EVENT_CREATED and uses a `__consumed__` marker to
        # originate the RFV/HPI exactly once whenever the stash becomes visible.
        effects = [
            rfv_stash.upsert(value=_intake_to_metadata_value(intake)),
            appointment.create(),
            task.apply(),
        ]
        if task_comment:
            # Surface the intake summary (symptom duration + any flagged med/allergy
            # changes) directly on the intake task, referencing it by the id we
            # assigned above, so the care team sees it while triaging the queue.
            effects.append(
                AddTaskComment(task_id=task_id, body=task_comment).apply()
            )

        return [
            *effects,
            JSONResponse(
                {
                    "ok": True,
                    "start_iso": start_iso,
                    "provider_name": match["provider_name"],
                    "duration_minutes": duration_minutes,
                    "modality": _resolve_modality(secrets.get("URGENT_CARE_VISIT_MODALITY")),
                    "appointments_url": "/app/appointments",
                }
            ),
        ]


