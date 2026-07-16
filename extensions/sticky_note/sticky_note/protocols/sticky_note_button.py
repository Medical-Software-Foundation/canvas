from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from django.db.models import Q

from logger import log

from sticky_note.models import StickyNote

SHOW_EVENT = EventType.Name(EventType.SHOW_CHART_PATIENT_HEADER_BUTTON)


class StickyNoteButton(ActionButton):
    """Chart-header button that opens the sticky note modal.

    The button reflects whether the patient has any sticky-note content visible to
    the current user (the shared note or the user's own note): filled shows a memo
    glyph on a yellow background, empty shows a no-entry glyph on a gray one. The
    appearance is recomputed on every chart render, so it tracks the note's state.
    """

    FILLED_BACKGROUND_COLOR = "#feff86"  # yellow — a sticky note has content
    EMPTY_BACKGROUND_COLOR = "#c7c7c7"  # gray — no content yet

    BUTTON_TITLE = "⛔ Sticky Note"
    BUTTON_KEY = "STICKY_NOTE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    BUTTON_BACKGROUND_COLOR = EMPTY_BACKGROUND_COLOR

    def _has_content(self) -> bool:
        """Whether the patient has a non-empty sticky note visible to the current user.

        Considers the shared note (``owner`` is null) and the current user's own note
        in a single query.
        """
        patient_id = self.event.target.id
        staff_id = self.event.context.get("user", {}).get("id", "")
        contents = (
            StickyNote.objects.filter(patient__id=patient_id)
            .filter(Q(owner__isnull=True) | Q(owner__id=staff_id))
            .values_list("content", flat=True)
        )
        return any(content and content.strip() for content in contents)

    def compute(self) -> list[Effect]:
        """Reflect the patient's sticky-note content in the button title and color."""
        log.info(
            "StickyNoteButton: Check if button has content"
        )
        filled = self._has_content()
        self.BUTTON_TITLE = "📝 Sticky Note" if filled else "⛔ Sticky Note"
        self.BUTTON_BACKGROUND_COLOR = (
            self.FILLED_BACKGROUND_COLOR if filled else self.EMPTY_BACKGROUND_COLOR
        )
        return super().compute()

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        staff_id = self.event.context.get("user", {}).get("id", "")
        auth_token = self.secrets.get("namespace_read_write_access_key", "")

        log.info(
            "StickyNoteButton: opened for patient %s by staff %s"
            % (patient_id, staff_id)
        )

        html = render_to_string(
            "templates/sticky_note.html",
            {
                "patient_id": patient_id,
                "staff_id": staff_id,
                "auth_token": auth_token,
            },
        )

        modal = LaunchModalEffect(
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            content=html,
        )
        return [modal.apply()]
