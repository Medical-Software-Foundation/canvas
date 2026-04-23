from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import (
    FormField,
    InputType,
    PatientMetadataCreateFormEffect,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class CcmatDiagnosisProtocol(BaseHandler):
    """Handler to add custom patient metadata fields for CCM Diagnosis."""
    RESPONDS_TO = EventType.Name(EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        """Add custom patient metadata fields for CCM Diagnosis."""
        form = PatientMetadataCreateFormEffect(form_fields=[
            FormField(
                key='ccm_diagnosis',
                label='CCM Diagnosis',
                type=InputType.TEXT,
                required=False,
                editable=True,
            ),
        ])

        return [form.apply()]
