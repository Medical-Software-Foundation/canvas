import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from logger import log


# Inherit from BaseProtocol to properly get registered for events
class Protocol(BaseProtocol):
    """You should put a helpful description of this protocol's behavior here."""

    # Name the event type you wish to run in response to
    RESPONDS_TO = EventType.Name(EventType.ASSESS_COMMAND__CONDITION_SELECTED)

    NARRATIVE_STRING = "I was inserted from my plugin's protocol."

    def compute(self) -> list[Effect]:
        """This method gets called when an event of the type RESPONDS_TO is fired."""
        # This class is initialized with several pieces of information you can
        # access.
        #
        # `self.event` is the event object that caused this method to be
        # called.
        #
        # `self.event.target.id` is an identifier for the object that is the subject of
        # the event. In this case, it would be the identifier of the assess
        # command. If this was a patient create event, it would be the
        # identifier of the patient. If this was a task update event, it would
        # be the identifier of the task. Etc, etc.
        # If the targeted model is already supported by the SDK,
        # you can retrieve the instance using `self.event.target.instance`
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
        log.info(self.NARRATIVE_STRING)

        # Craft a payload to be returned with the effect(s).
        payload = {
            "note": {"uuid": self.event.context["note"]["uuid"]},
            "data": {"narrative": self.NARRATIVE_STRING},
        }

        # Return zero, one, or many effects.
        # Example:
        return [Effect(type=EffectType.LOG, payload=json.dumps(payload))]
