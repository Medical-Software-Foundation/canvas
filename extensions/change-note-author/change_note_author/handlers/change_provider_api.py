"""HTTP route that applies a note author (provider) change.

The change-author modal POSTs the chosen staff member here. The route is gated on
a logged-in staff session, validates the inputs, and returns a Note update effect
that reassigns the note's provider.
"""

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.staff import Staff
from logger import log

from change_note_author.utils.matching import is_chart_review_note_type


def _error(message, status_code):
    return [JSONResponse({"ok": False, "error": message}, status_code=status_code)]


class ChangeProviderAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """POST /change-provider — reassign a note's author to a new active staff member."""

    PATH = "/change-provider"

    def post(self) -> list[Response | Effect]:
        try:
            payload = self.request.json()
        except (ValueError, TypeError):
            # Malformed or empty body from the client — expected, not a bug.
            return _error("Request body must be valid JSON.", HTTPStatus.BAD_REQUEST)

        if not isinstance(payload, dict):
            return _error("Request body must be a JSON object.", HTTPStatus.BAD_REQUEST)

        note_id = (payload.get("note_id") or "").strip()
        new_provider_id = (payload.get("new_provider_id") or "").strip()

        if not note_id:
            return _error("A note id is required.", HTTPStatus.BAD_REQUEST)
        if not new_provider_id:
            return _error("Please choose a provider.", HTTPStatus.BAD_REQUEST)

        note = Note.objects.filter(id=note_id).select_related("note_type_version").first()
        if note is None:
            return _error("That note could not be found.", HTTPStatus.NOT_FOUND)

        # The dropdown item is only rendered on Chart Review notes, but hiding a button
        # is not an access control — re-check the note type here so this route cannot be
        # used to reassign the author of any other note type.
        note_type_version = getattr(note, "note_type_version", None)
        note_type_name = getattr(note_type_version, "name", None)
        if not is_chart_review_note_type(note_type_name, self._chart_review_name()):
            log.warning(
                f"change_note_author: refused author change on note {note_id} "
                f"of type {note_type_name!r} (not a Chart Review note)"
            )
            return _error(
                "This plugin can only change the author of Chart Review notes.",
                HTTPStatus.FORBIDDEN,
            )

        new_provider = Staff.objects.filter(id=new_provider_id).first()
        if new_provider is None:
            return _error("The selected provider could not be found.", HTTPStatus.BAD_REQUEST)
        if not new_provider.active:
            return _error(
                "The selected provider is not active and cannot be assigned.",
                HTTPStatus.BAD_REQUEST,
            )

        current_provider = getattr(note, "provider", None)
        current_provider_id = getattr(current_provider, "id", None)
        if current_provider_id is not None and str(current_provider_id) == new_provider_id:
            return [
                JSONResponse(
                    {
                        "ok": True,
                        "noop": True,
                        "message": "That provider is already the author of this note.",
                    }
                )
            ]

        # Guard against editing a note the platform has locked/finalized, when we
        # can determine that state. If in doubt, we still attempt the update.
        if not self._note_is_editable(note):
            return _error(
                "This note is locked or finalized, so its author cannot be changed.",
                HTTPStatus.CONFLICT,
            )

        note_effect = NoteEffect(instance_id=note_id)
        note_effect.provider_id = new_provider_id

        log.info(
            f"change_note_author: staff {self._acting_staff_id()} reassigning note "
            f"{note_id} author to staff {new_provider_id}"
        )

        return [
            note_effect.update(),
            JSONResponse({"ok": True, "message": "The note's author has been updated."}),
        ]

    def _chart_review_name(self):
        return (self.secrets or {}).get("CHART_REVIEW_NOTE_TYPE_NAME")

    def _acting_staff_id(self):
        """The staff member making the change, for the audit trail.

        Canvas sets this header on every authenticated session request; the
        StaffSessionAuthMixin has already rejected anything without it.
        """
        return self.request.headers.get("canvas-logged-in-user-id") or "unknown"

    def _note_is_editable(self, note) -> bool:
        """Return True unless we can positively determine the note is not editable.

        If the platform doesn't expose a state we can read, don't block the user —
        let the update effect enforce its own rules.
        """
        current_state = getattr(note, "current_state", None)
        editable = getattr(current_state, "editable", None)
        if callable(editable):
            return bool(editable())
        return True
