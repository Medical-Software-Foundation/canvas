"""Stub canvas_sdk just enough for the plugin module to import in tests."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _ensure_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_canvas_sdk_stubs() -> None:
    _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    _ensure_module("canvas_sdk.v1.data")
    effects_mod = _ensure_module("canvas_sdk.effects")
    cmd_metadata_mod = _ensure_module("canvas_sdk.effects.command_metadata")
    events_mod = _ensure_module("canvas_sdk.events")
    handlers_mod = _ensure_module("canvas_sdk.handlers")
    command_data_mod = _ensure_module("canvas_sdk.v1.data.command")

    class Effect:
        def __init__(self, type=None, payload=None):
            self.type = type
            self.payload = payload

    class EffectType:
        COMMAND_AVAILABLE_ACTIONS_RESULTS = "COMMAND_AVAILABLE_ACTIONS_RESULTS"

    effects_mod.Effect = Effect
    effects_mod.EffectType = EffectType

    class InputType:
        TEXT = "TEXT"
        SELECT = "SELECT"
        DATE = "DATE"

    class FormField:
        def __init__(
            self,
            key,
            label,
            type,
            required=False,
            editable=True,
            options=None,
            value="",
        ):
            self.key = key
            self.label = label
            self.type = type
            self.required = required
            self.editable = editable
            self.options = options or []
            self.value = value

    class CommandMetadataCreateFormEffect:
        def __init__(self, command_uuid, form_fields):
            self.command_uuid = command_uuid
            self.form_fields = form_fields

        def apply(self):
            return self

    cmd_metadata_mod.CommandMetadataCreateFormEffect = CommandMetadataCreateFormEffect
    cmd_metadata_mod.FormField = FormField
    cmd_metadata_mod.InputType = InputType

    class EventType:
        COMMAND__FORM__GET_ADDITIONAL_FIELDS = 1
        PRESCRIBE_COMMAND__AVAILABLE_ACTIONS = 2

        @staticmethod
        def Name(value):
            mapping = {
                1: "COMMAND__FORM__GET_ADDITIONAL_FIELDS",
                2: "PRESCRIBE_COMMAND__AVAILABLE_ACTIONS",
            }
            return mapping.get(value, str(value))

    events_mod.EventType = EventType

    class BaseHandler:
        def __init__(self, event=None, secrets=None):
            self.event = event
            self.secrets = secrets or {}

    handlers_mod.BaseHandler = BaseHandler

    class CommandMetadata:
        objects = MagicMock()

    command_data_mod.CommandMetadata = CommandMetadata


_install_canvas_sdk_stubs()
