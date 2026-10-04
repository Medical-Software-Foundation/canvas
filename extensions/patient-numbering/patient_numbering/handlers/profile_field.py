from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import (
    FormField,
    InputType,
    PatientMetadataCreateFormEffect,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from patient_numbering.numbering import METADATA_KEY


class PatientNumberProfileField(BaseHandler):
    """Show the patient number as a read-only field in the profile's Demographics section."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        """Return the read-only Patient ID field. The value displayed comes from patient metadata."""
        form = PatientMetadataCreateFormEffect(
            form_fields=[
                FormField(
                    key=METADATA_KEY,
                    label="Patient ID",
                    type=InputType.TEXT,
                    required=False,
                    editable=False,
                ),
            ]
        )
        return [form.apply()]
