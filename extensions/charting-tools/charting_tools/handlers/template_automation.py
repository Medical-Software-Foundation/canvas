"""Puts one entry per active note template in the note body "/" menu."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.show_button import ShowButtonEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import Note
from logger import log

from charting_tools.insertion import template_effects
from charting_tools.models.note_template import NoteTemplate

# Button keys are shared across every plugin on the instance, so each
# template's key carries this prefix plus the template's own UUID.
BUTTON_KEY_PREFIX = "CHARTING_TOOLS__"


def button_key(template_id: str) -> str:
    """Return the "/" menu button key for a template."""
    return f"{BUTTON_KEY_PREFIX}{template_id}"


class NoteTemplateAutomation(ActionButton):
    """Lists templates in the "/" menu and inserts a template's commands when picked.

    ``ActionButton.compute`` shows a single fixed button, so this handler
    overrides it to emit one ``ShowButtonEffect`` per active template.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.SHOW_NOTE_BODY_AUTOMATION_BUTTON),
        EventType.Name(EventType.ACTION_BUTTON_CLICKED),
    ]

    BUTTON_TITLE = "Note template"
    BUTTON_KEY = BUTTON_KEY_PREFIX
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_BODY_AUTOMATION

    def compute(self) -> list[Effect]:
        """List templates on menu load; insert commands when one is clicked."""
        if self.event.type == EventType.SHOW_NOTE_BODY_AUTOMATION_BUTTON:
            return self._show_templates()
        key = str(self.event.context.get("key") or "")
        if self.event.type == EventType.ACTION_BUTTON_CLICKED and key.startswith(
            BUTTON_KEY_PREFIX
        ):
            return self.handle()
        return []

    def _show_templates(self) -> list[Effect]:
        if not self.event.context.get("note_id"):
            return []
        # show_in_menu is NULL on templates saved before the setting existed.
        templates = (
            NoteTemplate.objects.filter(active=True)
            .exclude(show_in_menu=False)
            .only("template_id", "name")
            .order_by("name")
        )
        return [
            ShowButtonEffect(
                key=button_key(template.template_id),
                title=template.name,
                priority=self.PRIORITY,
            ).apply()
            for template in templates
        ]

    def handle(self) -> list[Effect]:
        """Originate the clicked template's commands on the trigger line."""
        template_id = str(self.event.context["key"]).removeprefix(BUTTON_KEY_PREFIX)
        template = (
            NoteTemplate.objects.filter(template_id=template_id, active=True)
            .exclude(show_in_menu=False)
            .first()
        )
        if template is None:
            log.warning(f"Note template {template_id} not found or inactive")
            return []

        note = Note.objects.defer("body").filter(dbid=self.event.context.get("note_id")).first()
        if note is None:
            log.warning(f"Note {self.event.context.get('note_id')} not found")
            return []

        return template_effects(template, note, self.secrets, replace_line=True)
