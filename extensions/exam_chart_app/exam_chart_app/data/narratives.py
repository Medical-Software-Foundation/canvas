"""Per-command narrative storage for ROS / PE commands.

When `/exam/finalize` originates a ReviewOfSystemsCommand or
PhysicalExamCommand, the plugin-typed section-level narrative is
stashed here keyed by command_uuid. A separate BaseHandler reads it
back when the chart fires COMMAND__FORM__GET_ADDITIONAL_FIELDS for
that command, so the Narrative additional-field renders pre-filled
with the plugin's value.

Storage shape:
  AttributeHub(type=NAMESPACE, id=command_uuid).get_attribute("narrative")
"""
from __future__ import annotations

from canvas_sdk.v1.data import AttributeHub

NAMESPACE = "canvas__exam_chart_app"
NARRATIVE_KEY = "narrative"


def set_narrative(command_uuid: str, narrative: str) -> None:
    """Persist the section-level narrative for a ROS / PE command."""
    if not command_uuid:
        return
    hub, _ = AttributeHub.objects.get_or_create(type=NAMESPACE, id=command_uuid)
    hub.set_attribute(NARRATIVE_KEY, narrative)


def get_narrative(command_uuid: str) -> str:
    """Return the stored narrative for a command, or '' if none."""
    if not command_uuid:
        return ""
    hub = AttributeHub.objects.filter(type=NAMESPACE, id=command_uuid).first()
    if hub is None:
        return ""
    value = hub.get_attribute(NARRATIVE_KEY)
    return value if isinstance(value, str) else ""
