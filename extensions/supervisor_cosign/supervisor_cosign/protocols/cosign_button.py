import re

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.show_button import ShowButtonEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.staff import Staff

from supervisor_cosign.models.cosign_addendum import CoSignAddendum
from supervisor_cosign.models.cosign_record import CoSignRecord


SHOW_BUTTON_REGEX = re.compile(r"^SHOW_(.+?)_BUTTON$")


class CoSignButton(ActionButton):
    BUTTON_TITLE = "Co-sign"
    BUTTON_KEY = "COSIGN_BUTTON"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def compute(self) -> list[Effect]:
        # Override to provide a dynamic title based on co-sign status.
        if not self.BUTTON_LOCATION:
            return []

        show_match = SHOW_BUTTON_REGEX.fullmatch(self.event.name)
        if show_match:
            location = show_match.group(1)
            if self.ButtonLocation[location] != self.BUTTON_LOCATION:
                return []
            record = self._latest_record()
            if not record:
                return []
            title = "Co-signed ✓" if record.status == "approved" else "Co-sign"
            return [
                ShowButtonEffect(
                    key=self.BUTTON_KEY,
                    title=title,
                    priority=self.PRIORITY,
                ).apply()
            ]
        elif self.context.get("key") == self.BUTTON_KEY:
            return self.handle()
        return []

    def visible(self) -> bool:
        return self._latest_record() is not None

    def _latest_record(self) -> CoSignRecord | None:
        note_uuid = self._note_uuid()
        if not note_uuid:
            return None
        # Prefer approved over pending: if a cosign was already completed, show
        # that state - even if stale duplicate pending records exist.
        qs = CoSignRecord.objects.filter(note_id=note_uuid)
        approved = qs.filter(status="approved").order_by("-cosigned_at").first()
        if approved:
            return approved
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

        templates = [
            {
                "key": "teaching",
                "label": "Teaching physician - present & participated",
                "text": (
                    f"I was present for and participated in the critical and key portions of "
                    f"the examination and agree with {supervisee_name}'s findings and treatment plan."
                ),
            },
            {
                "key": "reviewed",
                "label": "Reviewed & agree",
                "text": (
                    f"I have reviewed {supervisee_name}'s documentation and agree with the "
                    f"assessment, findings, and plan as documented."
                ),
            },
            {
                "key": "personally_performed",
                "label": "Personally performed",
                "text": (
                    "I personally performed the service. I have reviewed and agree with "
                    "the documentation."
                ),
            },
            {
                "key": "custom",
                "label": "Custom (write your own)",
                "text": "",
            },
        ]

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
