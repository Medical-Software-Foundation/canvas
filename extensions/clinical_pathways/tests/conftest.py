"""Shared test fixtures and Canvas-SDK / Django stubs.

Stubs are installed at import time — before any test module imports plugin
code — so model and handler classes can be defined cleanly without real
Django or canvas_sdk available in the test environment. Tests then mock
behavior per-case rather than relying on real ORM / HTTP.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


def _ensure_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# ---------- Django stubs ----------


def _install_django_stubs() -> None:
    _ensure_module("django")
    _ensure_module("django.db")
    django_db_models = _ensure_module("django.db.models")

    class _FieldStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    for cls_name in (
        "TextField",
        "IntegerField",
        "BooleanField",
        "DateTimeField",
        "JSONField",
        "CharField",
        "ForeignKey",
        "Index",
        "UniqueConstraint",
    ):
        setattr(django_db_models, cls_name, type(cls_name, (_FieldStub,), {}))

    setattr(django_db_models, "DO_NOTHING", object())
    setattr(django_db_models, "CASCADE", object())

    class TextChoices:
        @classmethod
        def choices(cls) -> list[Any]:
            return []

    setattr(django_db_models, "TextChoices", TextChoices)


# ---------- canvas_sdk stubs ----------


class _StubEffect:
    """Stand-in for canvas_sdk Effect; carries a tag + payload for assertions."""

    def __init__(self, tag: str, payload: Any = None) -> None:
        self.tag = tag
        self.payload = payload

    def __repr__(self) -> str:
        return f"<_StubEffect tag={self.tag!r}>"


def _install_canvas_sdk_stubs() -> None:
    _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    _ensure_module("canvas_sdk.v1.data")
    base = _ensure_module("canvas_sdk.v1.data.base")

    class CustomModel:
        # Subclasses (Pathway, PathwayRun) declare class-level field descriptors
        # like `title = TextField()`. The TextField stub is a no-op so instances
        # need their own __init__ that just records kwargs as attributes.
        objects: Any = None

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

        def save(self) -> None:  # tests override with mocks where they care
            return None

    setattr(base, "CustomModel", CustomModel)

    # canvas_sdk.effects
    effects_mod = _ensure_module("canvas_sdk.effects")

    class Effect:
        pass

    setattr(effects_mod, "Effect", Effect)

    # canvas_sdk.effects.launch_modal
    launch_modal = _ensure_module("canvas_sdk.effects.launch_modal")

    class LaunchModalEffect:
        class TargetType:
            PAGE = "PAGE"
            RIGHT_CHART_PANE = "RIGHT_CHART_PANE"
            DEFAULT_MODAL = "DEFAULT_MODAL"

        def __init__(
            self, url: str = "", target: str = "", title: str = "",
        ) -> None:
            self.url = url
            self.target = target
            self.title = title

        def apply(self) -> _StubEffect:
            return _StubEffect(
                "LaunchModalEffect",
                {"url": self.url, "target": self.target, "title": self.title},
            )

    setattr(launch_modal, "LaunchModalEffect", LaunchModalEffect)

    # canvas_sdk.effects.batch_originate
    batch_originate = _ensure_module("canvas_sdk.effects.batch_originate")

    class BatchOriginateCommandEffect:
        def __init__(self, commands: list[Any] | None = None) -> None:
            self.commands = list(commands or [])

        def apply(self) -> _StubEffect:
            return _StubEffect("BatchOriginateCommandEffect", {"commands": self.commands})

    setattr(batch_originate, "BatchOriginateCommandEffect", BatchOriginateCommandEffect)

    # canvas_sdk.effects.simple_api
    simple_api_effects = _ensure_module("canvas_sdk.effects.simple_api")

    class Response:
        def __init__(
            self,
            body: bytes = b"",
            status_code: int = 200,
            content_type: str = "",
            headers: dict[str, str] | None = None,
        ) -> None:
            self.body = body
            self.status_code = status_code
            self.content_type = content_type
            self.headers = headers or {}

    class HTMLResponse(Response):
        def __init__(self, body: str, status_code: int = 200) -> None:
            super().__init__(
                body=body.encode() if isinstance(body, str) else body,
                status_code=status_code,
                content_type="text/html",
            )
            self.html = body

    class JSONResponse(Response):
        def __init__(self, data: Any, status_code: int = 200) -> None:
            super().__init__(
                body=str(data).encode(),
                status_code=status_code,
                content_type="application/json",
            )
            self.data = data

    setattr(simple_api_effects, "Response", Response)
    setattr(simple_api_effects, "HTMLResponse", HTMLResponse)
    setattr(simple_api_effects, "JSONResponse", JSONResponse)

    # canvas_sdk.handlers + subpackages
    handlers = _ensure_module("canvas_sdk.handlers")

    class BaseHandler:
        event: Any = None
        secrets: Any = None
        context: Any = None

    setattr(handlers, "BaseHandler", BaseHandler)

    application_mod = _ensure_module("canvas_sdk.handlers.application")

    class Application:
        context: Any = None

    setattr(application_mod, "Application", Application)

    action_button_mod = _ensure_module("canvas_sdk.handlers.action_button")

    class ActionButton:
        class ButtonLocation:
            NOTE_HEADER = "NOTE_HEADER"

        BUTTON_TITLE = ""
        BUTTON_KEY = ""
        BUTTON_LOCATION = ""
        context: Any = None
        target: Any = None

    setattr(action_button_mod, "ActionButton", ActionButton)

    simple_api_handlers = _ensure_module("canvas_sdk.handlers.simple_api")

    class _ApiDecoratorNamespace:
        """Stand-in for `canvas_sdk.handlers.simple_api.api` — every decorator
        returns the wrapped function unchanged so we can call routes directly."""

        @staticmethod
        def _decorator(_path: str) -> Any:
            def _wrap(fn: Any) -> Any:
                return fn

            return _wrap

        def get(self, path: str) -> Any:
            return self._decorator(path)

        def post(self, path: str) -> Any:
            return self._decorator(path)

        def put(self, path: str) -> Any:
            return self._decorator(path)

        def delete(self, path: str) -> Any:
            return self._decorator(path)

    class SimpleAPI:
        PREFIX = ""
        request: Any = None
        secrets: Any = None

    class StaffSessionAuthMixin:
        pass

    setattr(simple_api_handlers, "api", _ApiDecoratorNamespace())
    setattr(simple_api_handlers, "SimpleAPI", SimpleAPI)
    setattr(simple_api_handlers, "StaffSessionAuthMixin", StaffSessionAuthMixin)

    # canvas_sdk.templates
    templates_mod = _ensure_module("canvas_sdk.templates")

    def _fake_render(template_name: str, context: dict[str, Any] | None = None) -> str:
        ctx = context or {}
        return f"<<{template_name}::{sorted(ctx.keys())}>>"

    setattr(templates_mod, "render_to_string", _fake_render)

    # canvas_sdk.commands
    commands_mod = _ensure_module("canvas_sdk.commands")

    class QuestionnaireCommand:
        def __init__(self) -> None:
            self.note_uuid: str = ""
            self.command_uuid: str = ""
            self.questionnaire_id: str = ""

    setattr(commands_mod, "QuestionnaireCommand", QuestionnaireCommand)

    commands_pkg = _ensure_module("canvas_sdk.commands.commands")
    custom_command_mod = _ensure_module("canvas_sdk.commands.commands.custom_command")

    class CustomCommand:
        def __init__(
            self,
            schema_key: str = "",
            content: str = "",
            print_content: str = "",
        ) -> None:
            self.schema_key = schema_key
            self.content = content
            self.print_content = print_content
            self.command_uuid: str = ""
            self.note_uuid: str = ""

        def originate(self) -> _StubEffect:
            return _StubEffect(
                "CustomCommand.originate",
                {"schema_key": self.schema_key, "note_uuid": self.note_uuid},
            )

    setattr(custom_command_mod, "CustomCommand", CustomCommand)
    setattr(commands_pkg, "custom_command", custom_command_mod)

    # canvas_sdk.events
    events_mod = _ensure_module("canvas_sdk.events")

    class EventType:
        INTERVIEW_UPDATED = 42

        @classmethod
        def Name(cls, value: int) -> str:
            return "INTERVIEW_UPDATED"

    setattr(events_mod, "EventType", EventType)

    # canvas_sdk.v1.data.note
    note_mod = _ensure_module("canvas_sdk.v1.data.note")

    class Note:
        objects: Any = None

    Note.DoesNotExist = type("DoesNotExist", (Exception,), {})

    class CurrentNoteStateEvent:
        objects: Any = None

    CurrentNoteStateEvent.DoesNotExist = type("DoesNotExist", (Exception,), {})

    setattr(note_mod, "Note", Note)
    setattr(note_mod, "CurrentNoteStateEvent", CurrentNoteStateEvent)

    # canvas_sdk.v1.data.questionnaire
    questionnaire_mod = _ensure_module("canvas_sdk.v1.data.questionnaire")

    class Questionnaire:
        objects: Any = None

    class Interview:
        objects: Any = None

    setattr(questionnaire_mod, "Questionnaire", Questionnaire)
    setattr(questionnaire_mod, "Interview", Interview)

    # logger.log — module-level `log` with the methods we call.
    logger_mod = _ensure_module("logger")
    setattr(logger_mod, "log", MagicMock(name="logger.log"))


# Install stubs immediately at conftest import time so all subsequent test
# imports (including the plugin modules under test) resolve cleanly.
_install_django_stubs()
_install_canvas_sdk_stubs()


# ---------- Shared fixtures ----------


@pytest.fixture
def stub_effect_type() -> type:
    """Expose the _StubEffect class so tests can assert effect tags."""
    return _StubEffect
