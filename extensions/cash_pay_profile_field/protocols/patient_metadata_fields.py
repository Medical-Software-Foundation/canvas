from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import (
    PatientMetadataCreateFormEffect,
    InputType,
    FormField,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class PatientMetadataFields(BaseHandler):
    """Adds the 'Cash Pay Patient?' single-select field to the patient profile.

    The selected value (``"Yes"`` or ``"No"``) is persisted as patient metadata
    under the key ``cash_pay_patient``. The field is optional, so a blank value
    is a valid state and never blocks saving the profile.
    """

    RESPONDS_TO = EventType.Name(EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        form = PatientMetadataCreateFormEffect(
            form_fields=[
                FormField(
                    key="cash_pay_patient",
                    label="Cash Pay Patient",
                    type=InputType.SELECT,
                    required=False,
                    editable=True,
                    options=["Yes", "No"],
                ),
            ]
        )

        return [form.apply()]
