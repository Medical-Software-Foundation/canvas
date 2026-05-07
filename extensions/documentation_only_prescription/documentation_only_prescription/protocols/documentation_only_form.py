from __future__ import annotations

import json

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.effects.command_metadata import (
    CommandMetadataCreateFormEffect,
    FormField,
    InputType,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data.command import CommandMetadata

PRESCRIBE_SCHEMA_KEY = "prescribe"

DOCUMENTATION_ONLY_KEY = "documentation_only"
DOCUMENTATION_ONLY_LABEL = "Documentation only"
# Single-option SELECT: choosing "Yes" marks the prescription as documentation
# only; an empty/unset value is treated as the implicit "No".
DOCUMENTATION_ONLY_OPTIONS = ["Yes"]
DOCUMENTATION_ONLY_TRUE_VALUE = "Yes"

# Actions removed from the Prescribe command when documentation_only == Yes.
# `sign_action` is intentionally retained so the user can still sign the
# documentation-only entry. Both pre-commit (`sign_send_action`) and post-commit
# (`send_action`) transmission paths are blocked, along with print in either
# state. The home app uses `print_action` pre-commit and `print` post-commit, so
# both names are listed here.
ACTIONS_TO_REMOVE_WHEN_DOC_ONLY = frozenset(
    {"sign_send_action", "send_action", "print_action", "print"}
)


class DocumentationOnlyFormHandler(BaseHandler):
    """Render a 'Documentation only' Yes/No field on the Prescribe command."""

    RESPONDS_TO = EventType.Name(EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        if self.event.context.get("schema_key") != PRESCRIBE_SCHEMA_KEY:
            return []

        return [
            CommandMetadataCreateFormEffect(
                command_uuid=self.event.target.id,
                form_fields=[
                    FormField(
                        key=DOCUMENTATION_ONLY_KEY,
                        label=DOCUMENTATION_ONLY_LABEL,
                        type=InputType.SELECT,
                        options=DOCUMENTATION_ONLY_OPTIONS,
                        required=False,
                        editable=True,
                    ),
                ],
            ).apply()
        ]


class DocumentationOnlyActionFilter(BaseHandler):
    """Filter sign-and-send, send, and print actions when documentation_only == Yes; sign is retained."""

    RESPONDS_TO = EventType.Name(EventType.PRESCRIBE_COMMAND__AVAILABLE_ACTIONS)

    def compute(self) -> list[Effect]:
        actions = self.event.context.get("actions", [])

        entry = CommandMetadata.objects.filter(
            command__id=self.event.target.id,
            key=DOCUMENTATION_ONLY_KEY,
        ).first()
        stored_value = (entry.value or "").strip() if entry else ""

        if stored_value != DOCUMENTATION_ONLY_TRUE_VALUE:
            return []

        filtered_actions = [
            action
            for action in actions
            if action.get("name") not in ACTIONS_TO_REMOVE_WHEN_DOC_ONLY
        ]

        return [
            Effect(
                type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS,
                payload=json.dumps(filtered_actions),
            )
        ]
