"""Prescription Favorites Application and API handlers."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from logger import log

from prescription_favorites.services import FavoritesService


class PrescriptionFavoritesApp(Application):
    """Right chart application displaying prescription favorites catalog."""

    def on_open(self) -> Effect:
        """Handle the on_open event - render the UI."""
        patient = Patient.objects.get(id=self.event.context["patient"]["id"])

        # Get most recently modified open note (single query)
        notes = list(self._get_all_open_notes(patient))
        most_recent_note = notes[0] if notes else None
        has_open_notes = len(notes) > 0

        log.info(f"Opening Prescribing for patient {patient.id}, {len(notes)} open notes")

        # Get logged-in staff ID for visibility filtering
        # Try multiple context paths - the available keys vary by SDK version
        staff_id = (
            self.event.context.get("staff", {}).get("id", "")
            or self.event.context.get("user", {}).get("id", "")
            or ""
        )
        log.info(f"Staff ID: {staff_id}, context keys: {list(self.event.context.keys())}")

        # Get all favorites (hardcoded + custom) from FavoritesService
        # If staff_id is missing, fall back to shared-only to avoid exposing private favorites
        service = FavoritesService()
        if staff_id:
            all_favorites = service.get_all_favorites(staff_id=staff_id)
        else:
            log.warning("No staff ID in context - showing shared favorites only")
            all_favorites = service.get_all_favorites(visibility_filter="shared")

        return LaunchModalEffect(
            content=render_to_string(
                "templates/favorites_template.html",
                {
                    "has_open_notes": has_open_notes,
                    "patient_id": patient.id,
                    "medications": all_favorites,
                },
            ),
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Prescribing",
        ).apply()

    def _get_all_open_notes(self, patient: Patient):  # type: ignore[no-untyped-def]
        """Get all open notes for the patient, ordered by most recent."""
        open_note_states = [
            NoteStates.NEW,
            NoteStates.PUSHED,
            NoteStates.CONVERTED,
            NoteStates.UNLOCKED,
            NoteStates.RESTORED,
            NoteStates.UNDELETED,
        ]

        open_note_ids = CurrentNoteStateEvent.objects.filter(
            state__in=open_note_states
        ).values_list("note_id", flat=True)

        return Note.objects.filter(dbid__in=open_note_ids, patient=patient).order_by(
            "-modified"
        )
