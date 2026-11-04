from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.staff import Staff

from supervisor_cosign.helpers.attestation_templates import (
    DEFAULT_TEMPLATE_KEY,
    attestation_options,
)
from supervisor_cosign.helpers.viewer_cosign import viewer_owes_cosign
from supervisor_cosign.models.cosign_addendum import CoSignAddendum
from supervisor_cosign.models.cosign_record import CoSignRecord



class CoSignButton(ActionButton):
    """Co-sign in the note footer, where the native Sign button is hidden for this viewer.

    Shown only to the supervisor on a pending record for a locked or signed note, so it
    disappears once the co-sign is approved. With COSIGN_REOPEN_ON_AMEND on, it returns
    when the supervisee amends and re-signs the note.
    """

    BUTTON_TITLE = "Co-sign"
    BUTTON_KEY = "COSIGN_FOOTER_BUTTON"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_FOOTER
    BUTTON_BACKGROUND_COLOR = "#21ba45"
    BUTTON_TEXT_COLOR = "#ffffff"
    RESPONDS_TO = [
        EventType.Name(EventType.SHOW_NOTE_FOOTER_BUTTON),
        EventType.Name(EventType.ACTION_BUTTON_CLICKED),
    ]

    def visible(self) -> bool:
        return viewer_owes_cosign(self._note_uuid(), self.event.actor.id)

    def _latest_record(self) -> CoSignRecord | None:
        note_uuid = self._note_uuid()
        if not note_uuid:
            return None
        # Prefer pending: an amended note carries its earlier approved record alongside
        # the pending one it now owes, and the modal should offer the attestation form.
        qs = CoSignRecord.objects.filter(note_id=note_uuid)
        pending = qs.filter(status="pending").order_by("-selected_at").first()
        if pending:
            return pending
        return qs.order_by("-selected_at").first()

    def handle(self) -> list[Effect]:
        note_uuid = self._note_uuid()
        if not note_uuid:
            return []

        record = self._latest_record()
        if not record:
            return []

        note = Note.objects.select_related("patient").filter(id=note_uuid).first()
        if note is None:
            return []
        patient = note.patient
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else ""
        note_date = note.datetime_of_service.strftime("%Y-%m-%d") if note.datetime_of_service else ""

        supervisee_name = self._staff_name(record.supervisee_id) or "the provider"

        addendum_entries = [
            {
                "text": entry["addendum_text"],
                "supervisor_name": entry["supervisor_name"],
                "created_at": entry["created_at"].strftime("%Y-%m-%d %H:%M UTC") if entry["created_at"] else "",
            }
            for entry in CoSignAddendum.objects.filter(note_id=note_uuid)
            .order_by("created_at")
            .values("addendum_text", "supervisor_name", "created_at")
        ]

        templates = attestation_options(supervisee_name)

        context = {
            "note_id": note_uuid,
            "patient_name": patient_name,
            "note_date": note_date,
            "supervisee_name": supervisee_name,
            "approved": record.status == "approved",
            "cosigned_on": record.cosigned_at.strftime("%Y-%m-%d %H:%M UTC") if record.cosigned_at else "",
            "supervisor_name": self._staff_name(record.supervisor_id),
            "addendum_entries": addendum_entries,
            "templates": templates,
            "default_template": DEFAULT_TEMPLATE_KEY,
        }

        content = render_to_string("templates/cosign_modal.html", context)
        return [LaunchModalEffect(content=content).apply()]

    def _note_uuid(self) -> str | None:
        raw = self.context.get("note_id")
        if raw is None or raw == "":
            return None
        note = Note.objects.filter(dbid=raw).values_list("id", flat=True).first()
        return str(note) if note else None

    def _staff_name(self, staff_id: str) -> str:
        if not staff_id:
            return ""
        staff = Staff.objects.filter(id=staff_id).values("first_name", "last_name").first()
        if not staff:
            return ""
        return f"{staff['first_name']} {staff['last_name']}"
