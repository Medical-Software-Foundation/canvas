from __future__ import annotations

import json
from typing import Any

from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

DELEGATE_ACTION_NAME = "delegate_action"


def actions_without_delegate(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the available-action list with the Delegate action removed."""
    return [action for action in actions if action.get("name") != DELEGATE_ACTION_NAME]


class DisableImagingOrderDelegate(BaseHandler):
    """Disable the Delegate action on the Image command, leaving Sign only."""

    RESPONDS_TO = EventType.Name(EventType.IMAGING_ORDER_COMMAND__AVAILABLE_ACTIONS)

    def compute(self) -> list[Effect]:
        actions = actions_without_delegate(self.event.context["actions"])
        return [
            Effect(
                type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS,
                payload=json.dumps(actions),
            )
        ]


class DisableReferDelegate(BaseHandler):
    """Disable the Delegate action on the Refer command, leaving Sign only."""

    RESPONDS_TO = EventType.Name(EventType.REFER_COMMAND__AVAILABLE_ACTIONS)

    def compute(self) -> list[Effect]:
        actions = actions_without_delegate(self.event.context["actions"])
        return [
            Effect(
                type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS,
                payload=json.dumps(actions),
            )
        ]
