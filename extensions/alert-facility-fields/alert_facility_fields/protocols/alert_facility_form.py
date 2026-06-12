from __future__ import annotations

from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect
from canvas_sdk.effects.command_metadata import (
    CommandMetadataCreateFormEffect,
    FormField,
    InputType,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import CommandMetadata

SUPPORTED_SCHEMA_KEYS = frozenset({"medicationStatement", "stopMedication"})
ALERT_FACILITY_KEY = "alert_facility"
ALERT_FACILITY_LABEL = "Alert facility"
ALERT_FACILITY_OPTIONS = ["Yes", "No"]
REQUIRED_ERROR_MESSAGE = "Alert Facility is a required field."


class AlertFacilityFormHandler(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        if self.event.context.get("schema_key") not in SUPPORTED_SCHEMA_KEYS:
            return []

        # Pass the previously-stored value through so reopening a committed
        # command shows the saved choice instead of a blank dropdown.
        existing_value = (
            CommandMetadata.objects.filter(
                command__id=self.event.target.id,
                key=ALERT_FACILITY_KEY,
            )
            .values_list("value", flat=True)
            .first()
        )

        return [
            CommandMetadataCreateFormEffect(
                command_uuid=self.event.target.id,
                form_fields=[
                    FormField(
                        key=ALERT_FACILITY_KEY,
                        label=ALERT_FACILITY_LABEL,
                        type=InputType.SELECT,
                        options=ALERT_FACILITY_OPTIONS,
                        required=True,
                        editable=True,
                        value=existing_value,
                    ),
                ],
            ).apply()
        ]


class AlertFacilityRequiredValidator(BaseHandler):
    RESPONDS_TO = [
        EventType.Name(EventType.MEDICATION_STATEMENT_COMMAND__POST_VALIDATION),
        EventType.Name(EventType.STOP_MEDICATION_COMMAND__POST_VALIDATION),
    ]

    def compute(self) -> list[Effect]:
        entry = CommandMetadata.objects.filter(
            command__id=self.event.target.id,
            key=ALERT_FACILITY_KEY,
        ).first()
        if entry is None or not (entry.value or "").strip():
            return [
                CommandValidationErrorEffect()
                .add_error(REQUIRED_ERROR_MESSAGE)
                .apply()
            ]
        return []
