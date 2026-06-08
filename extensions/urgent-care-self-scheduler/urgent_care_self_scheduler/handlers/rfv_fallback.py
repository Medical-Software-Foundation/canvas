import json
from typing import Any

from canvas_sdk.commands import HistoryOfPresentIllnessCommand, ReasonForVisitCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import PatientMetadata
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log

EXTERNAL_ID_SYSTEM = "urgent-care-self-scheduler"
PENDING_RFV_KEY_PREFIX = "pending_rfv_"
CONSUMED_MARKER = "__consumed__"


def _correlation_id_from_appointment(appointment: Any) -> str | None:
    """Returns the urgent-care correlation UUID from the appointment's external
    identifiers, or None if this appointment wasn't created by our plugin.
    """
    for ext in appointment.external_identifiers.all():
        if getattr(ext, "system", None) == EXTERNAL_ID_SYSTEM:
            return str(ext.value)
    return None


def _format_review_section(
    title: str,
    review: dict,
    *,
    none_label: str,
    item_kind: str,
) -> list[str]:
    """Renders a meds- or allergies-style review block as plaintext lines."""
    if review.get("no_changes"):
        return [f"{title}: No changes reported."]
    changes = review.get("changes") or []
    if not changes:
        return [f"{title}: No changes flagged."]
    lines = [f"{title} — patient flagged:"]
    for c in changes:
        label = (c.get("label") or "").strip() or none_label
        note = (c.get("note") or "").strip()
        lines.append(f"  • {label}" + (f" ({note})" if note else ""))
    return lines


def _build_hpi_narrative(intake: dict) -> str:
    """Builds a free-text HPI summary from the intake payload."""
    sections: list[list[str]] = []

    duration = (intake.get("symptom_duration") or "").strip()
    if duration:
        sections.append([f"Symptom duration: {duration}"])

    sections.append(
        _format_review_section(
            "Medications",
            intake.get("medications") or {},
            none_label="Unknown medication",
            item_kind="medication",
        )
    )
    sections.append(
        _format_review_section(
            "Allergies",
            intake.get("allergies") or {},
            none_label="Unknown allergy",
            item_kind="allergy",
        )
    )

    # Join with a single blank line between sections.
    return "\n\n".join("\n".join(section) for section in sections).rstrip()


class UrgentCareRfvOriginator(BaseHandler):
    """Listens for new appointments. If the appointment was created by this plugin
    (matched via external_identifier system), reads the patient's stashed intake
    payload, originates the ReasonForVisitCommand on the encounter note, and marks
    the metadata as consumed so we don't re-process on subsequent events.

    Listens to two events to handle the BookAPI compute() effect-ordering race:
    APPOINTMENT_CREATED can fire before the PatientMetadata.upsert effect lands,
    so we also catch NOTE_STATE_CHANGE_EVENT_CREATED (which fires later in the
    sequence). The `__consumed__` marker keeps it idempotent.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED),
    ]

    def _resolve_appointment(self) -> Any:
        from canvas_sdk.v1.data.appointment import Appointment

        # Pull FK targets (note, patient) and the external_identifiers list in
        # the same query so the rest of compute() doesn't fan out to 5+ queries.
        base = Appointment.objects.select_related("note", "patient").prefetch_related(
            "external_identifiers"
        )
        if self.event.type == EventType.APPOINTMENT_CREATED:
            try:
                return base.get(id=self.event.target.id)
            except Appointment.DoesNotExist:
                return None

        # NOTE_STATE_CHANGE_EVENT_CREATED — find the appointment via the note.
        note_uuid = self.event.context.get("note_id")
        if not note_uuid:
            return None
        return base.filter(note__id=note_uuid).first()

    def compute(self) -> list[Effect]:
        appointment = self._resolve_appointment()
        if appointment is None:
            log.warning(
                f"UrgentCareRfvOriginator: could not resolve appointment from event "
                f"({EventType.Name(self.event.type)})"
            )
            return []

        correlation_id = _correlation_id_from_appointment(appointment)
        if not correlation_id:
            return []  # Not one of ours.

        if not appointment.note:
            log.warning(
                f"UrgentCareRfvOriginator: appointment {appointment.id} has no linked note"
            )
            return []

        metadata_key = f"{PENDING_RFV_KEY_PREFIX}{correlation_id}"
        metadata_record = appointment.patient.metadata.filter(key=metadata_key).first()
        if not metadata_record:
            # Likely the effect-ordering race: APPOINTMENT_CREATED can fire before
            # the intake stash commits. The companion NOTE_STATE_CHANGE event retries,
            # so a single occurrence here is expected, not a definitive lost intake.
            log.info(
                f"UrgentCareRfvOriginator: no intake metadata yet for {correlation_id} "
                f"(patient {appointment.patient.id}); will retry on the companion event"
            )
            return []
        if not metadata_record.value or metadata_record.value == CONSUMED_MARKER:
            # Benign: the other event already originated the RFV/HPI. Logged (not
            # silent) so it's distinguishable from the missing-stash case above.
            log.info(
                f"UrgentCareRfvOriginator: intake for {correlation_id} already consumed; skipping"
            )
            return []

        try:
            intake = json.loads(metadata_record.value)
        except (json.JSONDecodeError, TypeError) as e:
            log.error(
                f"UrgentCareRfvOriginator: malformed intake JSON for {correlation_id}: {e}"
            )
            return []

        rfv_text = (intake.get("reason_for_visit") or "").strip()
        if not rfv_text:
            log.warning(
                f"UrgentCareRfvOriginator: empty reason_for_visit in metadata for {correlation_id}"
            )
            return []

        note_uuid = str(appointment.note.id)
        effects: list[Effect] = []

        # Originate both commands STAGED (uncommitted). The patient-entered reason
        # and intake narrative are pre-filled on the note for the provider to review
        # and commit during the visit — clinician confirmation, not auto-finalized.
        # (Inline `originate(commit=True)` is also rejected server-side for the
        # reasonForVisit command: "Command with key reasonForVisit is not committable".)
        rfv_command = ReasonForVisitCommand(note_uuid=note_uuid, comment=rfv_text)
        effects.append(rfv_command.originate())

        hpi_narrative = _build_hpi_narrative(intake)
        if hpi_narrative:
            hpi_command = HistoryOfPresentIllnessCommand(
                note_uuid=note_uuid, narrative=hpi_narrative
            )
            effects.append(hpi_command.originate())

        clear_metadata = PatientMetadata(
            patient_id=str(appointment.patient.id),
            key=metadata_key,
        )
        effects.append(clear_metadata.upsert(value=CONSUMED_MARKER))

        log.info(
            f"UrgentCareRfvOriginator: originating RFV + HPI on note {appointment.note.id} "
            f"for appointment {appointment.id}"
        )
        return effects
