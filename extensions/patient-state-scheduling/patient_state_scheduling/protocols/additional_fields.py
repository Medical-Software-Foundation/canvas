from canvas_sdk.effects import Effect
from canvas_sdk.effects.appointments_metadata import (
    AppointmentsMetadataCreateFormEffect,
    FormField,
    InputType,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

# Full names of all 50 US states plus DC. The value shown in the dropdown is
# also the value stored on the appointment and the key looked up in the
# LOCATION_MAPPING secret consumed by LocationFilterHandler, so these strings
# must match the keys used there.
US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
]


class AdditionalFieldsHandler(BaseHandler):
    """Add a "Patient's Current State" dropdown to the appointment scheduling form.

    Staff select the state the patient is currently located in (asked during
    scheduling, not derived from the patient's address). LocationFilterHandler
    uses the selection to filter the practice-location dropdown.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        form = AppointmentsMetadataCreateFormEffect(
            form_fields=[
                FormField(
                    key="state",
                    label="Patient's Current State",
                    type=InputType.SELECT,
                    required=False,
                    editable=True,
                    options=US_STATES,
                ),
            ]
        )
        return [form.apply()]
