"""Scheduling application that replaces Canvas's built-in scheduling modal.

Because this handler subclasses ``SchedulingApplication``, Canvas routes every
scheduling entry point through it — the schedule page, the patient chart, the
calendar's drag-to-create and reschedule interactions, and the reschedule
action inside a note. Each surface supplies a different slice of context
(see ``scheduling_context``); ``on_open`` forwards whatever arrived as query
params on the modal URL so the modal opens pre-populated.

https://docs.canvasmedical.com/sdk/handlers-embedded-applications/#scheduling-applications
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import SchedulingApplication

from scheduling_with_rooms.utils.scheduling_context import (
    ENTITY_PARAMS,
    SCALAR_PARAMS,
    modal_url,
)


class SchedulingWithRoomsApp(SchedulingApplication):
    """Opens the rooms-aware scheduling modal for every scheduling action."""

    NAME = "Schedule Appointment"
    IDENTIFIER = "scheduling_with_rooms__scheduler"

    def on_open(self) -> Effect:
        """Launch the scheduling modal, carrying the launch context with it."""
        context = self.event.context or {}
        params: dict[str, str] = {}

        # Entities arrive as {"id": <external id>}; forward just the id and let
        # the /modal endpoint resolve it into something displayable.
        for context_key, param in ENTITY_PARAMS.items():
            entity = context.get(context_key)
            entity_id = str(entity.get("id") or "").strip() if isinstance(entity, dict) else ""
            if entity_id:
                params[param] = entity_id

        for context_key in SCALAR_PARAMS:
            value = context.get(context_key)
            if value not in (None, ""):
                params[context_key] = str(value)

        reschedule = params.get("mode") == "reschedule"
        return LaunchModalEffect(
            url=modal_url(**params),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Reschedule Appointment" if reschedule else "Schedule Appointment",
        ).apply()
