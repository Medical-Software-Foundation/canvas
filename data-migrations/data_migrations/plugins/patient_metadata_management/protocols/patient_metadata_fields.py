from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import PatientMetadataCreateFormEffect, InputType, FormField
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


METADATA_VALIDATION = {
    "other_legal_names": {
        "type": "string"
    },
    "marital_status": {
        "type": "string",
        "options": [
            "Annulled",
            "Divorced",
            "Interlocutory",
            "Legally Separated",
            "Married",
            "Common Law",
            "Polygamous",
            "Domestic partner",
            "Unmarried",
            "Never Married",
            "Widowed",
            "Unknown"
        ]
    },
    "intake_form_complete": {
        "type": "date",
        "format": "YYYY-MM-DD"
    }
}

# Inherit from BaseHandler to properly get registered for events
class PatientMetadataFields(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        """
            This protocol defines all of the unique patient metadata fields to showcase
            on the patient's profile page. 
            
            See documentation on the PatientMetadataCreateFormEffect: 
            https://docs.canvasmedical.com/sdk/patient-metadata-create-form-effect/
        """


        form = PatientMetadataCreateFormEffect(form_fields=[
            FormField(
                key='other_legal_names',
                label='Any Other Legal Names (e.g., a different last name) in the Past',
                type=InputType.TEXT,
                required=False,
                editable=True,
            ),
            FormField(
                key='marital_status',
                label='Marital Status',
                type=InputType.SELECT,
                required=False,
                editable=True,
                options=METADATA_VALIDATION["marital_status"]['options']
            ),
            FormField(
                key='intake_form_complete',
                label='Intake Form Complete',
                type=InputType.DATE,
                required=False,
                editable=True,
            )
        ])

        return [form.apply()]

