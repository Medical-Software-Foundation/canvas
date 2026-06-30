"""Shared fixtures and mock module setup for group_therapy tests.

Canvas SDK is not installable via pip — it's provided by the Canvas runtime.
We install stub modules so test collection doesn't fail on import.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ------------------------------------------------------------------ #
#  Stub base classes that the plugin source code inherits from
# ------------------------------------------------------------------ #

class _StubSimpleAPI:
    """Stub for canvas_sdk.handlers.simple_api.SimpleAPI."""
    pass


class _StubStaffSessionAuthMixin:
    """Stub for canvas_sdk.handlers.simple_api.security.StaffSessionAuthMixin."""
    pass


class _StubBaseProtocol:
    """Stub for canvas_sdk.protocols.BaseProtocol."""
    RESPONDS_TO = []

    @property
    def target(self):
        return getattr(self, 'event', MagicMock()).target

    def compute(self):
        return []


class _StubApplication:
    """Stub for canvas_sdk.handlers.application.Application."""
    pass


class _StubCustomModel:
    """Stub for canvas_sdk.v1.data.base.CustomModel (subclassed by our models)."""
    pass


class _StubApi:
    """Stub for the @api.get / @api.post decorator namespace."""

    @staticmethod
    def get(path):
        def decorator(fn):
            return fn
        return decorator

    @staticmethod
    def post(path):
        def decorator(fn):
            return fn
        return decorator


class _StubResponse:
    """Stub for canvas_sdk.effects.simple_api.Response."""
    pass


class _StubJSONResponse:
    """Stub for canvas_sdk.effects.simple_api.JSONResponse."""
    def __init__(self, data=None, status_code=200):
        self.data = data
        self.status_code = status_code


class _StubHTMLResponse:
    """Stub for canvas_sdk.effects.simple_api.HTMLResponse."""
    def __init__(self, html="", status_code=200):
        self.html = html
        self.status_code = status_code


class _StubEffect:
    """Stub for canvas_sdk.effects.Effect."""
    def __init__(self, type="", payload=""):
        self.type = type
        self.payload = payload


class _StubEventType:
    """Stub for canvas_sdk.events.EventType."""
    class Name:
        def __init__(self, val=None):
            pass

    ASSESS_COMMAND__POST_COMMIT = "ASSESS_COMMAND__POST_COMMIT"
    DIAGNOSE_COMMAND__POST_COMMIT = "DIAGNOSE_COMMAND__POST_COMMIT"


# ------------------------------------------------------------------ #
#  Build mock module tree
# ------------------------------------------------------------------ #

def _make_mock_module(name: str) -> ModuleType:
    """Create a module that returns MagicMock for unknown attributes."""
    cls = type(name, (ModuleType,), {"__getattr__": lambda self, k: MagicMock()})
    mod = cls(name)
    mod.__all__ = []
    return mod


# All canvas_sdk submodules referenced by group_therapy source code
_MOCK_MODULES = [
    "canvas_sdk",
    "canvas_sdk.commands",
    "canvas_sdk.commands.commands",
    "canvas_sdk.commands.commands.assess",
    "canvas_sdk.commands.commands.custom_command",
    "canvas_sdk.commands.commands.diagnose",
    "canvas_sdk.commands.commands.perform",
    "canvas_sdk.commands.commands.questionnaire",
    "canvas_sdk.commands.commands.questionnaire.question",
    "canvas_sdk.effects",
    "canvas_sdk.effects.batch_originate",
    "canvas_sdk.effects.billing_line_item",
    "canvas_sdk.effects.launch_modal",
    "canvas_sdk.effects.note",
    "canvas_sdk.effects.note.note",
    "canvas_sdk.effects.note.appointment",
    "canvas_sdk.effects.simple_api",
    "canvas_sdk.events",
    "canvas_sdk.handlers",
    "canvas_sdk.handlers.application",
    "canvas_sdk.handlers.simple_api",
    "canvas_sdk.handlers.simple_api.security",
    "canvas_sdk.protocols",
    "canvas_sdk.v1",
    "canvas_sdk.v1.data",
    "canvas_sdk.v1.data.base",
    "canvas_sdk.v1.data.appointment",
    "canvas_sdk.v1.data.command",
    "canvas_sdk.v1.data.condition",
    "canvas_sdk.v1.data.medication",
    "canvas_sdk.v1.data.note",
    "canvas_sdk.v1.data.patient",
    "canvas_sdk.v1.data.practicelocation",
    "canvas_sdk.v1.data.staff",
    "canvas_sdk.value_set",
    "canvas_sdk.value_set.value_set",
    "logger",
    "django",
    "django.db",
    "django.db.models",
]


def pytest_configure(config):
    """Install mock modules before test collection."""
    for mod_name in _MOCK_MODULES:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = _make_mock_module(mod_name)

    # Patch specific attributes that need to be real classes (not MagicMock)
    # so that class inheritance works in source files.
    sys.modules["canvas_sdk.effects"].Effect = _StubEffect
    sys.modules["canvas_sdk.effects.simple_api"].JSONResponse = _StubJSONResponse
    sys.modules["canvas_sdk.effects.simple_api"].HTMLResponse = _StubHTMLResponse
    sys.modules["canvas_sdk.effects.simple_api"].Response = _StubResponse
    sys.modules["canvas_sdk.events"].EventType = _StubEventType
    sys.modules["canvas_sdk.protocols"].BaseProtocol = _StubBaseProtocol
    sys.modules["canvas_sdk.handlers.application"].Application = _StubApplication
    sys.modules["canvas_sdk.v1.data.base"].CustomModel = _StubCustomModel
    sys.modules["canvas_sdk.handlers.simple_api"].SimpleAPI = _StubSimpleAPI
    sys.modules["canvas_sdk.handlers.simple_api"].api = _StubApi()
    sys.modules["canvas_sdk.handlers.simple_api.security"].StaffSessionAuthMixin = _StubStaffSessionAuthMixin

    # logger stub
    sys.modules["logger"].log = MagicMock()


# ------------------------------------------------------------------ #
#  Shared fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def mock_event():
    """Create a mock event with a target ID."""
    event = MagicMock()
    event.target = "command-uuid-123"
    return event


@pytest.fixture
def mock_command():
    """Create a mock Command with a note."""
    command = MagicMock()
    command.note.id = "note-uuid-123"
    command.note.dbid = "note-db-id-123"
    return command


@pytest.fixture
def mock_request():
    """Create a mock HTTP request."""
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": "staff-123"}
    request.query_params = {}
    return request
