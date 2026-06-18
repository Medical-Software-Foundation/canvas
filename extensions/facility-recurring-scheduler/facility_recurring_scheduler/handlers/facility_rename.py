from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.appointment import ScheduleEvent
from canvas_sdk.events import EventType
from canvas_sdk.v1.data import Appointment as AppointmentModel, AppointmentMetadata
from canvas_sdk.v1.data.note import NoteTypeCategories
from logger import log

from facility_recurring_scheduler.utils.constants import FIELD_FACILITY_KEY


class FacilityRename(BaseHandler):
    """Automatically renames Other Events to display the selected facility name.

    When an Other Event is created with a facility selected, this handler
    updates the event's description to the facility name.

    For child events (recurring), it looks up the parent's facility metadata
    and applies the same name. Uses .update() to bypass allow_custom_title validation.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        try:
            appointment = AppointmentModel.objects.select_related("note_type").get(
                id=self.event.target.id
            )
        except AppointmentModel.DoesNotExist:
            log.warning(f"FacilityRename: appointment {self.event.target.id} not found, skipping")
            return []

        # Only process schedule events (Other Events), not regular appointments
        if appointment.note_type.category != NoteTypeCategories.SCHEDULE_EVENT:
            return []

        facility_name = None

        # Check if this is a child event (has a parent)
        if appointment.parent_appointment_id:
            # Get facility name from parent's metadata
            facility_name = AppointmentMetadata.objects.filter(
                appointment_id=appointment.parent_appointment_id,
                key=FIELD_FACILITY_KEY
            ).values_list("value", flat=True).first()
        else:
            # Get facility name from this appointment's metadata
            facility_name = AppointmentMetadata.objects.filter(
                appointment=appointment, key=FIELD_FACILITY_KEY
            ).values_list("value", flat=True).first()

        if not facility_name:
            log.info(f"No facility found for appointment {appointment.id}, skipping rename")
            return []

        # Update the event description to the facility name using .update()
        # This bypasses the allow_custom_title validation that applies on .create()
        log.info(f"Renaming appointment {appointment.id} to facility '{facility_name}'")
        event_effect = ScheduleEvent(instance_id=str(appointment.id))
        event_effect.description = facility_name
        return [event_effect.update()]
