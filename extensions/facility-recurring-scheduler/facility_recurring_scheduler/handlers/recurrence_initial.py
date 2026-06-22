from zoneinfo import ZoneInfo

from canvas_sdk.effects.note.appointment import ScheduleEvent, Appointment
from canvas_sdk.events import EventType
from canvas_sdk.v1.data import Appointment as AppointmentModel, AppointmentMetadata
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import NoteTypeCategories
from canvas_sdk.effects import Effect
from logger import log

from facility_recurring_scheduler.utils.constants import (
    RecurrenceEnum,
    FIELD_RECURRENCE_KEY,
    INITIAL_BATCH_COUNT,
)
from facility_recurring_scheduler.utils.recurrence import calculate_recurrence_date
from facility_recurring_scheduler.utils.timezone_helper import get_timezone_for_appointment


class RecurrenceInitialHandler(BaseHandler):
    """Creates recurring child events when a recurring appointment or schedule event is created.

    Handles BOTH regular appointments and schedule events (Other Events).
    Creates child events with parent_appointment_id linking back to the parent.

    Note: Description is NOT set on child events. The FacilityRename handler
    will update the description after each event is created.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def _get_recurrence_from_appointment_metadata(
        self, appointment: AppointmentModel
    ) -> str:
        """Determine the recurrence type from the appointment metadata."""
        recurrence = AppointmentMetadata.objects.filter(
            appointment=appointment, key=FIELD_RECURRENCE_KEY
        ).values_list("value", flat=True).first()

        return recurrence or RecurrenceEnum.NONE.value

    def _create_child_appointment(
        self,
        appointment: AppointmentModel,
        count: int,
        recurrence: str,
        patient_id: str | None,
        local_tz: ZoneInfo,
    ) -> Appointment:
        """Create a child appointment for regular appointments."""
        new_start_time = calculate_recurrence_date(
            appointment.start_time, count, recurrence, local_tz
        )

        return Appointment(
            patient_id=patient_id,
            parent_appointment_id=str(appointment.id),
            start_time=new_start_time,
            duration_minutes=appointment.duration_minutes,
            provider_id=str(appointment.provider.id),
            practice_location_id=str(appointment.location.id),
            meeting_link=appointment.meeting_link,
            appointment_note_type_id=str(appointment.note_type.id),
        )

    def _create_child_event(
        self,
        appointment: AppointmentModel,
        count: int,
        recurrence: str,
        patient_id: str | None = None,
        *,
        local_tz: ZoneInfo,
    ) -> ScheduleEvent:
        """Create a child schedule event for Other Events."""
        new_start_time = calculate_recurrence_date(
            appointment.start_time, count, recurrence, local_tz
        )

        return ScheduleEvent(
            patient_id=patient_id,
            parent_appointment_id=str(appointment.id),
            start_time=new_start_time,
            duration_minutes=appointment.duration_minutes,
            practice_location_id=str(appointment.location.id),
            provider_id=str(appointment.provider.id),
            note_type_id=str(appointment.note_type.id),
        )

    def compute(self) -> list[Effect]:
        try:
            parent_appointment: AppointmentModel = AppointmentModel.objects.select_related(
                "note_type", "provider", "location", "patient"
            ).get(id=self.event.target.id)
        except AppointmentModel.DoesNotExist:
            log.warning(f"RecurrenceInitial: appointment {self.event.target.id} not found, skipping")
            return []

        # Skip if this is already a child event (has a parent) - prevents infinite loops
        if parent_appointment.parent_appointment_id:
            log.info(f"Skipping child event {parent_appointment.id} (has parent)")
            return []

        recurrence = self._get_recurrence_from_appointment_metadata(parent_appointment)
        if not recurrence or recurrence == RecurrenceEnum.NONE.value:
            return []

        batch_count = INITIAL_BATCH_COUNT.get(recurrence)
        if batch_count is None:
            log.warning(f"RecurrenceInitial: unknown recurrence type {recurrence!r} for parent {parent_appointment.id}")
            return []

        is_schedule_event = (
            parent_appointment.note_type.category == NoteTypeCategories.SCHEDULE_EVENT
        )

        patient_id = self.event.context.get("patient", {}).get("id")

        # Cache timezone once for all iterations
        local_tz = get_timezone_for_appointment(parent_appointment, patient_id)

        effects = []
        for i in range(1, batch_count + 1):
            try:
                if is_schedule_event:
                    effect = self._create_child_event(
                        parent_appointment, i, recurrence, patient_id, local_tz=local_tz
                    )
                else:
                    effect = self._create_child_appointment(
                        parent_appointment, i, recurrence, patient_id, local_tz
                    )
                effects.append(effect.create())
            except Exception:
                log.exception(f"RecurrenceInitial: error creating child {i} for parent {parent_appointment.id}, skipping")
                continue

        log.info(f"RecurrenceInitial: created {len(effects)} {recurrence} events for parent {parent_appointment.id}")
        return effects
