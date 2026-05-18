"""Pytest fixtures and Canvas SDK stubs for the vitalstream plugin tests.

The real canvas_sdk package is not installed in the test environment, so we
register lightweight stubs in sys.modules before any plugin code is imported.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Stub hierarchy for canvas_sdk and logger.
# ---------------------------------------------------------------------------


def _make_stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


def _ensure(*names: str) -> None:
    for name in names:
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            prefix = ".".join(parts[:i])
            if prefix not in sys.modules:
                _make_stub(prefix)


_ensure(
    "canvas_sdk",
    "canvas_sdk.caching",
    "canvas_sdk.caching.plugins",
    "canvas_sdk.commands",
    "canvas_sdk.commands.commands",
    "canvas_sdk.commands.commands.custom_command",
    "canvas_sdk.effects",
    "canvas_sdk.effects.launch_modal",
    "canvas_sdk.effects.note",
    "canvas_sdk.effects.note.note",
    "canvas_sdk.effects.observation",
    "canvas_sdk.effects.simple_api",
    "canvas_sdk.handlers",
    "canvas_sdk.handlers.action_button",
    "canvas_sdk.handlers.simple_api",
    "canvas_sdk.handlers.simple_api.websocket",
    "canvas_sdk.templates",
    "canvas_sdk.v1",
    "canvas_sdk.v1.data",
    "canvas_sdk.v1.data.command",
    "canvas_sdk.v1.data.note",
    "canvas_sdk.v1.data.staff",
    "logger",
)


# --- canvas_sdk.caching.plugins ---------------------------------------------
sys.modules["canvas_sdk.caching.plugins"].get_cache = MagicMock()


# --- canvas_sdk.effects ------------------------------------------------------
sys.modules["canvas_sdk.effects"].Effect = type("Effect", (), {})


# --- canvas_sdk.effects.launch_modal ----------------------------------------
class _TargetType:
    RIGHT_CHART_PANE_LARGE = "RIGHT_CHART_PANE_LARGE"
    NOTE = "NOTE"


class _LaunchModalEffect:
    TargetType = _TargetType

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def apply(self) -> Any:
        return self


sys.modules["canvas_sdk.effects.launch_modal"].LaunchModalEffect = _LaunchModalEffect


# --- canvas_sdk.effects.note.note -------------------------------------------
sys.modules["canvas_sdk.effects.note.note"].Note = MagicMock


# --- canvas_sdk.effects.observation -----------------------------------------
_obs = sys.modules["canvas_sdk.effects.observation"]
_obs.CodingData = MagicMock
_obs.Observation = MagicMock
_obs.ObservationComponentData = MagicMock


# --- canvas_sdk.effects.simple_api ------------------------------------------
class _Broadcast:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def apply(self) -> Any:
        return self


class _Response:
    def __init__(self, content: Any = b"", status_code: int = 200, content_type: str = "") -> None:
        self.content = content
        self.status_code = status_code
        self.content_type = content_type


class _HTMLResponse(_Response):
    pass


class _JSONResponse(_Response):
    def __init__(self, data: Any = None, status_code: int = 200) -> None:
        super().__init__(content=data, status_code=status_code)
        self.data = data


_sa = sys.modules["canvas_sdk.effects.simple_api"]
_sa.Broadcast = _Broadcast
_sa.Response = _Response
_sa.HTMLResponse = _HTMLResponse
_sa.JSONResponse = _JSONResponse


# --- canvas_sdk.handlers.simple_api -----------------------------------------
class _SimpleAPI:
    pass


class _StaffSessionAuthMixin:
    pass


class _APIKeyAuthMixin:
    pass


class _Credentials:
    pass


class _Api:
    @staticmethod
    def _decorator(*_args: Any, **_kwargs: Any) -> Any:
        def wrap(fn: Any) -> Any:
            return fn
        return wrap

    get = staticmethod(_decorator)
    post = staticmethod(_decorator)
    put = staticmethod(_decorator)
    delete = staticmethod(_decorator)


_hs = sys.modules["canvas_sdk.handlers.simple_api"]
_hs.SimpleAPI = _SimpleAPI
_hs.StaffSessionAuthMixin = _StaffSessionAuthMixin
_hs.APIKeyAuthMixin = _APIKeyAuthMixin
_hs.Credentials = _Credentials
_hs.api = _Api()


# --- canvas_sdk.handlers.simple_api.websocket -------------------------------
class _WebSocketAPI:
    pass


sys.modules["canvas_sdk.handlers.simple_api.websocket"].WebSocketAPI = _WebSocketAPI


# --- canvas_sdk.handlers.action_button --------------------------------------
class _ButtonLocation:
    NOTE_HEADER = "NOTE_HEADER"


class _ActionButton:
    ButtonLocation = _ButtonLocation


sys.modules["canvas_sdk.handlers.action_button"].ActionButton = _ActionButton


# --- canvas_sdk.templates ---------------------------------------------------
sys.modules["canvas_sdk.templates"].render_to_string = MagicMock(
    return_value="<html>rendered</html>"
)


# --- canvas_sdk.commands.commands.custom_command ----------------------------
sys.modules["canvas_sdk.commands.commands.custom_command"].CustomCommand = MagicMock


# --- canvas_sdk.v1.data.note -------------------------------------------------
_v1_note = sys.modules["canvas_sdk.v1.data.note"]
_v1_note.Note = MagicMock()


class _NoteStates:
    LOCKED = "LOCKED"
    NEW = "NEW"


_v1_note.NoteStates = _NoteStates
_v1_note.CurrentNoteStateEvent = MagicMock()


# --- canvas_sdk.v1.data.staff ------------------------------------------------
sys.modules["canvas_sdk.v1.data.staff"].Staff = MagicMock()


# --- canvas_sdk.v1.data.command ---------------------------------------------
sys.modules["canvas_sdk.v1.data.command"].Command = MagicMock()


# --- logger -----------------------------------------------------------------
sys.modules["logger"].log = MagicMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_canvas_mocks() -> None:
    """Reset shared MagicMocks between tests to avoid cross-test pollution."""
    for name in [
        "canvas_sdk.caching.plugins",
        "canvas_sdk.templates",
        "canvas_sdk.v1.data.note",
        "canvas_sdk.v1.data.staff",
        "canvas_sdk.v1.data.command",
        "logger",
    ]:
        mod = sys.modules[name]
        for attr in dir(mod):
            if attr.startswith("_"):
                continue
            obj = getattr(mod, attr)
            if isinstance(obj, MagicMock):
                obj.reset_mock()


@pytest.fixture()
def mock_request() -> MagicMock:
    """Return a bare request mock; configure `.json`, `.headers`, etc. per test."""
    return MagicMock()
