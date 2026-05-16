"""Attach a Narrative additional-field to ROS / PE commands on the chart.

Canonical SDK pattern:

  - BaseHandler responds to COMMAND__FORM__GET_ADDITIONAL_FIELDS
  - Filters by `schema_key` from the event context
  - Returns CommandMetadataCreateFormEffect with the field schema

For pre-filling, the narrative stashed by /exam/finalize is read back
from AttributeHub keyed by the same command_uuid (see
`data/narratives.py`).
"""
from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.command_metadata import (
    CommandMetadataCreateFormEffect,
    FormField,
    InputType,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from exam_chart_app.data.narratives import get_narrative

SUPPORTED_SCHEMA_KEYS = frozenset({"ros", "exam"})
NARRATIVE_KEY = "narrative"
NARRATIVE_LABEL = "Narrative"


class ExamSectionAdditionalFieldsHandler(BaseHandler):
    """Render a Narrative additional-field on ROS and PE commands."""

    RESPONDS_TO = EventType.Name(EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        if self.event.context.get("schema_key") not in SUPPORTED_SCHEMA_KEYS:
            return []

        command_uuid = self.event.target.id
        existing_value = get_narrative(str(command_uuid)) if command_uuid else ""

        return [
            CommandMetadataCreateFormEffect(
                command_uuid=command_uuid,
                form_fields=[
                    FormField(
                        key=NARRATIVE_KEY,
                        label=NARRATIVE_LABEL,
                        type=InputType.TEXT,
                        required=False,
                        editable=True,
                        value=existing_value,
                    ),
                ],
            ).apply()
        ]
