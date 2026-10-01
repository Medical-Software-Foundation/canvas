"""Tests for the delegate-action-disabling handlers."""

import json
from unittest.mock import MagicMock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from disable_delegate_on_image_and_refer.handlers.disable_delegate_actions import (
    DisableImagingOrderDelegate,
    DisableReferDelegate,
    actions_without_delegate,
)

STAGED_ACTIONS = [
    {"name": "sign_action", "label": "Sign"},
    {"name": "delegate_action", "label": "Delegate"},
]


def _event_with_actions(actions: list[dict]) -> MagicMock:
    event = MagicMock()
    event.context = {"actions": [dict(action) for action in actions]}
    return event


class TestActionsWithoutDelegate:
    """Tests for the pure filter helper."""

    def test_removes_delegate_only(self) -> None:
        result = actions_without_delegate([dict(a) for a in STAGED_ACTIONS])
        assert [a["name"] for a in result] == ["sign_action"]

    def test_noop_when_delegate_absent(self) -> None:
        actions = [{"name": "sign_action"}, {"name": "enter_in_error"}]
        result = actions_without_delegate([dict(a) for a in actions])
        assert [a["name"] for a in result] == ["sign_action", "enter_in_error"]


class TestDisableImagingOrderDelegate:
    """Tests for the Image command handler."""

    def test_responds_to_imaging_available_actions(self) -> None:
        assert DisableImagingOrderDelegate.RESPONDS_TO == EventType.Name(
            EventType.IMAGING_ORDER_COMMAND__AVAILABLE_ACTIONS
        )

    def test_removes_delegate_keeps_sign(self) -> None:
        effects = DisableImagingOrderDelegate(_event_with_actions(STAGED_ACTIONS)).compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS

        names = [action["name"] for action in json.loads(effects[0].payload)]
        assert "delegate_action" not in names
        assert "sign_action" in names


class TestDisableReferDelegate:
    """Tests for the Refer command handler."""

    def test_responds_to_refer_available_actions(self) -> None:
        assert DisableReferDelegate.RESPONDS_TO == EventType.Name(
            EventType.REFER_COMMAND__AVAILABLE_ACTIONS
        )

    def test_removes_delegate_keeps_sign(self) -> None:
        effects = DisableReferDelegate(_event_with_actions(STAGED_ACTIONS)).compute()

        assert len(effects) == 1
        assert effects[0].type == EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS

        names = [action["name"] for action in json.loads(effects[0].payload)]
        assert "delegate_action" not in names
        assert "sign_action" in names
