from canvas_sdk.handlers import BaseHandler
from canvas_sdk.effects.appointments_metadata import (
    FormField,
    InputType,
    AppointmentsMetadataCreateFormEffect,
)
from canvas_sdk.events import EventType
from canvas_sdk.effects import Effect
from canvas_sdk.v1.data.facility import Facility
from logger import log

from facility_recurring_scheduler.utils.constants import (
    FIELD_FACILITY_KEY,
    FIELD_RECURRENCE_KEY,
    RecurrenceEnum,
)


class OtherEventFormFields(BaseHandler):
    """Adds custom dropdown fields to the scheduling modal.

    Recurrence is shown for all event types (appointments and schedule events).
    Facility is only shown for schedule events (Other Events tab).
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        form_fields = []
        is_schedule_event = self.event.context.get("category") == "schedule_event"

        # Facility dropdown — only for Other Events (schedule events)
        if is_schedule_event:
            try:
                facility_options = list(
                    Facility.objects.filter(active=True).order_by("name").values_list("name", flat=True)
                )
                form_fields.append(
                    FormField(
                        key=FIELD_FACILITY_KEY,
                        label="Facility",
                        type=InputType.SELECT,
                        required=False,
                        options=facility_options,
                    )
                )
                log.info(f"Including facility field with {len(facility_options)} options")
            except Exception:
                log.exception("Failed to load facility options, continuing without facility field")

        # Recurrence dropdown — available for all event types
        form_fields.append(
            FormField(
                key=FIELD_RECURRENCE_KEY,
                label="Recurrence",
                type=InputType.SELECT,
                required=False,
                options=[item.value for item in RecurrenceEnum],
            )
        )

        log.info(f"Returning {len(form_fields)} form fields for category {self.event.context.get('category')!r}")
        return [
            AppointmentsMetadataCreateFormEffect(form_fields=form_fields).apply()
        ]
