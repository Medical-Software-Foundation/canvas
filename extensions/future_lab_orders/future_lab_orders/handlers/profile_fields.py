"""Adds the future lab order fields to the patient profile."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_metadata import (
    FormField,
    InputType,
    PatientMetadataCreateFormEffect,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.lab import LabPartner

from future_lab_orders.fields import DUE_DATE_KEY, LAB_KEY, TESTS_KEY


class FutureLabOrderProfileFields(BaseHandler):
    """Shows Lab, Tests and Due date fields in the patient profile.

    The lab is a dropdown of the instance's active lab partners. If the
    instance has none, it is a free-text field.
    """

    RESPONDS_TO = EventType.Name(EventType.PATIENT_METADATA__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        """Return the form fields."""
        lab_names = list(
            LabPartner.objects.filter(active=True)
            .exclude(name="")
            .order_by("name")
            .values_list("name", flat=True)
            .distinct()
        )
        if lab_names:
            lab_field = FormField(
                key=LAB_KEY,
                label="Future lab order: lab",
                type=InputType.SELECT,
                required=False,
                editable=True,
                options=lab_names,
            )
        else:
            lab_field = FormField(
                key=LAB_KEY,
                label="Future lab order: lab",
                type=InputType.TEXT,
                required=False,
                editable=True,
            )

        return [
            PatientMetadataCreateFormEffect(
                form_fields=[
                    lab_field,
                    FormField(
                        key=TESTS_KEY,
                        label="Future lab order: tests",
                        type=InputType.TEXT,
                        required=False,
                        editable=True,
                    ),
                    FormField(
                        key=DUE_DATE_KEY,
                        label="Future lab order: due date",
                        type=InputType.DATE,
                        required=False,
                        editable=True,
                    ),
                ]
            ).apply()
        ]
