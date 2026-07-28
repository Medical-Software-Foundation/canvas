"""Note-header dropdown button that opens a modal to change a Chart Review note's
author (provider)."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.staff import Staff
from logger import log

from change_note_author.utils.matching import (
    initials,
    is_chart_review_note_type,
    staff_display_name,
    staff_subtitle,
)


class ChangeProvidersButton(ActionButton):
    """Adds "Change providers" to the note header's three-dots (dropdown) menu.

    The item only appears on Chart Review notes. Clicking it launches a centered
    modal that lists active staff and posts the chosen author back to the plugin's
    HTTP route.
    """

    BUTTON_TITLE = "Change providers"
    BUTTON_KEY = "change_note_author"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER_DROPDOWN
    # Lower values appear higher in the menu; push this item toward the top.
    PRIORITY = -100

    def _get_note(self):
        """Look up the note this button is being rendered for, or None.

        ``visible()`` runs on every note header render, so the note type is joined
        in rather than fetched as a second query.
        """
        note_dbid = (self.event.context or {}).get("note_id")
        if not note_dbid:
            return None
        return (
            Note.objects.filter(dbid=note_dbid).select_related("note_type_version").first()
        )

    def _chart_review_name(self):
        return (self.secrets or {}).get("CHART_REVIEW_NOTE_TYPE_NAME")

    def visible(self) -> bool:
        """Only show the item on Chart Review notes."""
        note = self._get_note()
        if note is None:
            return False

        note_type_version = getattr(note, "note_type_version", None)
        note_type_name = getattr(note_type_version, "name", None)
        return is_chart_review_note_type(note_type_name, self._chart_review_name())

    def handle(self) -> list[Effect]:
        """Build and launch the change-author modal."""
        note = self._get_note()
        if note is None:
            log.warning("ChangeProvidersButton clicked but note could not be found.")
            return []

        current_provider = getattr(note, "provider", None)
        current_provider_id = getattr(current_provider, "id", None)

        staff_options = []
        # `credentialed_name` and `top_clinical_role` both read `staff.roles`, which
        # would otherwise fire one query per staff member.
        for staff in Staff.objects.filter(active=True).prefetch_related("roles"):
            name = staff_display_name(staff)
            subtitle = staff_subtitle(staff)
            staff_options.append(
                {
                    "id": str(staff.id),
                    "name": name,
                    "subtitle": subtitle,
                    "search": f"{name} {subtitle}".strip().lower(),
                    "is_current": str(staff.id) == str(current_provider_id),
                }
            )

        staff_options.sort(key=lambda option: option["name"].lower())

        current_provider_name = (
            staff_display_name(current_provider) if current_provider else "Unassigned"
        )

        context = {
            "note_id": str(note.id),
            "current_provider_name": current_provider_name,
            "current_provider_initials": initials(current_provider_name),
            "current_provider_id": str(current_provider_id) if current_provider_id else "",
            "staff_options": staff_options,
        }

        content = render_to_string("templates/change_provider.html", context)

        return [
            LaunchModalEffect(
                content=content,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Change providers",
            ).apply()
        ]
