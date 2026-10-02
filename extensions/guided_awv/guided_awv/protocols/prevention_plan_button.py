"""ActionButton to generate and display the Personalized Prevention Plan."""

from html import escape as html_escape

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from logger import log


class PreventionPlanButton(ActionButton):
    """Note header button that generates and displays the prevention plan in a Canvas modal."""

    BUTTON_TITLE = "Prevention Plan"
    BUTTON_KEY = "AWV_PREVENTION_PLAN"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        """Only show on AWV note types (SNOMED 401131001) - matches GuidedAWVApp.visible()."""
        note_id = self.event.context.get("note_id")
        if not note_id:
            return False
        try:
            from canvas_sdk.v1.data.note import Note

            from guided_awv.constants import is_awv_note_type

            note = Note.objects.select_related("note_type_version").get(dbid=note_id)
            return is_awv_note_type(note.note_type_version)
        except Exception:
            return False

    def handle(self) -> list[Effect]:
        """Generate the prevention plan and open it in a Canvas modal."""
        note_dbid = self.event.context.get("note_id")
        patient_id = str(self.event.target.id or "")

        # Look up note UUID from dbid
        note_uuid = ""
        try:
            from canvas_sdk.v1.data.note import Note

            note = Note.objects.get(dbid=note_dbid)
            note_uuid = str(note.id)
        except Exception as e:
            log.warning(f"[PreventionPlanButton] Could not resolve note UUID: {e}")
            return []

        if not note_uuid or not patient_id:
            log.warning("[PreventionPlanButton] Missing note_uuid or patient_id")
            return []

        try:
            from guided_awv.api.awv_api import GeneratePreventionPlanHandler

            # Subclass to create a lightweight instance without SimpleAPIRoute init args.
            # Python's normal class instantiation calls __new__/__init__ internally
            # without triggering the sandbox's dunder attribute access restriction.
            class PlanBuilder(GeneratePreventionPlanHandler):
                def __init__(self) -> None:
                    self.request = None

            builder = PlanBuilder()
            html = builder._build_plan(note_uuid, patient_id)
        except Exception as e:
            log.error(f"[PreventionPlanButton] Failed to build plan: {e}", exc_info=True)
            # Escape exception text to prevent HTML injection if str(e) contains
            # special characters from cached form-state (defense-in-depth).
            safe_err = html_escape(str(e))
            error_html = (
                f'<div style="padding:40px;text-align:center;font-family:sans-serif;">'
                f'<h2>Error Generating Prevention Plan</h2>'
                f'<p>{safe_err}</p>'
                f'<p>Make sure AWV sections have been saved before generating the plan.</p>'
                f'</div>'
            )
            modal = LaunchModalEffect(
                content=error_html,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="Prevention Plan Error",
            )
            return [modal.apply()]

        modal = LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Personalized Prevention Plan",
        )
        return [modal.apply()]
