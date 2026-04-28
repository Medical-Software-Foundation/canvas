import json

from canvas_sdk.commands import GoalCommand
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient
from logger import log

# Inherit from BaseHandler to properly get registered for events
class NewOfficeVisitNoteHandler(BaseHandler):
    """Originates goal command when a new office visit note is created."""

    # Name the event type you wish to run in response to
    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        """This method gets called when an event of the type RESPONDS_TO is fired."""
        # This class is initialized with several pieces of information you can
        # access.
        #
        # `self.event` is the event object that caused this method to be
        # called.
        #
        # `self.event.target.id` is an identifier for the object that is the subject of
        # the event. In this case, it would be the identifier of the note state.
        #
        # `self.event.context` is a python dictionary of additional data that was
        # given with the event. The information given here depends on the
        # event type.
        #
        # `self.secrets` is a python dictionary of the secrets you defined in
        # your CANVAS_MANIFEST.json and set values for in the uploaded
        # plugin's configuration page: <emr_base_url>/admin/plugin_io/plugin/<plugin_id>/change/
        # Example: self.secrets['WEBHOOK_URL']

        # You can log things and see them using the Canvas CLI's log streaming
        # function.
        log.info(f"[NewOfficeVisitNoteHandler] Context: {self.event.context}")

        # Get the note state from context
        note_state = self.event.context.get("state")

        # Check if the note state is NEW
        if note_state != "NEW":
            return []

        # Get the note ID from context and fetch the Note object
        note_id = self.event.context.get("note_id")
        note = Note.objects.get(id=note_id)

        # Check if note type is OFFICE VISIT
        note_type_name = note.note_type_version.name

        if note_type_name != "Office visit":
            return []

        # Get the note UUID from context (it's already a UUID string)
        note_uuid = note_id

        # Get the patient to create a personalized goal statement
        patient_id = self.event.context.get("patient_id")
        patient = Patient.objects.get(id=patient_id)
        patient_name = patient.first_name
        goal_statement = f"{patient_name} will build plugins with the Canvas SDK to improve their clinical workflow"

        # Create and originate Goal command with personalized statement
        goal_command = GoalCommand(note_uuid=note_uuid, goal_statement=goal_statement)

        return [goal_command.originate()]
