"""Shared test fixtures and Django/Canvas-SDK stubs.

The plugin depends on canvas_sdk and on Django. In the test environment neither is
available so we stub just enough of the surface area to let the plugin modules import
cleanly. Tests then mock behavior per-case rather than relying on real ORM / HTTP.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


def _ensure_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_django_stubs() -> None:
    django = _ensure_module("django")
    django_db = _ensure_module("django.db")
    django_db_models = _ensure_module("django.db.models")

    class _FieldStub:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    for cls in (
        "TextField",
        "IntegerField",
        "DateField",
        "DateTimeField",
        "BooleanField",
        "ForeignKey",
        "Index",
        "UniqueConstraint",
    ):
        setattr(django_db_models, cls, type(cls, (_FieldStub,), {}))

    class Q:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __or__(self, other):
            return self

        def __and__(self, other):
            return self

    django_db_models.Q = Q
    django_db_models.PROTECT = "PROTECT"
    django_db_models.DO_NOTHING = "DO_NOTHING"

    class _IntegrityError(Exception):
        pass

    django_db.IntegrityError = _IntegrityError

    class _Transaction:
        @staticmethod
        def atomic():
            import contextlib

            @contextlib.contextmanager
            def _cm():
                yield

            return _cm()

    django_db.transaction = _Transaction()

    sys.modules["django.db"] = django_db
    sys.modules["django.db.models"] = django_db_models


def _install_canvas_sdk_stubs() -> None:
    sdk = _ensure_module("canvas_sdk")
    v1 = _ensure_module("canvas_sdk.v1")
    data = _ensure_module("canvas_sdk.v1.data")
    effects_mod = _ensure_module("canvas_sdk.effects")
    launch_modal_mod = _ensure_module("canvas_sdk.effects.launch_modal")
    simple_api_effects = _ensure_module("canvas_sdk.effects.simple_api")
    handlers_mod = _ensure_module("canvas_sdk.handlers")
    app_mod = _ensure_module("canvas_sdk.handlers.application")
    simple_api_mod = _ensure_module("canvas_sdk.handlers.simple_api")
    templates_mod = _ensure_module("canvas_sdk.templates")
    base_mod = _ensure_module("canvas_sdk.v1.data.base")
    custom_data_mod = _ensure_module("canvas_sdk.v1.data.custom_data")

    class CustomModel:
        objects = MagicMock()

        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class ModelExtension:
        pass

    class Staff:
        objects = MagicMock()

    data.Staff = Staff
    data.ModelExtension = ModelExtension
    data.CustomModel = CustomModel
    base_mod.CustomModel = CustomModel
    custom_data_mod.CustomModel = CustomModel

    class Effect:
        pass

    effects_mod.Effect = Effect

    class LaunchModalEffect:
        class TargetType:
            DEFAULT_MODAL = "DEFAULT_MODAL"

        def __init__(self, url, target, title=""):
            self.url = url
            self.target = target
            self.title = title

        def apply(self):
            return ("LaunchModalEffect", self.url, self.target, self.title)

    launch_modal_mod.LaunchModalEffect = LaunchModalEffect

    class Response:
        def __init__(self, body=b"", status_code=200, content_type="text/plain", headers=None):
            self.body = body
            self.status_code = status_code
            self.content_type = content_type
            self.headers = headers or {}

    class HTMLResponse(Response):
        def __init__(self, body, status_code=200):
            super().__init__(body=body, status_code=status_code, content_type="text/html")

    class JSONResponse(Response):
        def __init__(self, data, status_code=200):
            self.data = data
            super().__init__(body=b"", status_code=status_code, content_type="application/json")

    simple_api_effects.Response = Response
    simple_api_effects.HTMLResponse = HTMLResponse
    simple_api_effects.JSONResponse = JSONResponse

    class Application:
        pass

    app_mod.Application = Application

    class StaffSessionAuthMixin:
        pass

    class SimpleAPI:
        pass

    class _RouteDecorator:
        def __init__(self, method, path):
            self.method = method
            self.path = path

        def __call__(self, func):
            func.__api_route__ = (self.method, self.path)
            return func

    class _Api:
        def get(self, path):
            return _RouteDecorator("GET", path)

        def post(self, path):
            return _RouteDecorator("POST", path)

        def patch(self, path):
            return _RouteDecorator("PATCH", path)

        def delete(self, path):
            return _RouteDecorator("DELETE", path)

    simple_api_mod.SimpleAPI = SimpleAPI
    simple_api_mod.StaffSessionAuthMixin = StaffSessionAuthMixin
    simple_api_mod.api = _Api()

    def render_to_string(template_name, context=None):
        return f"RENDERED::{template_name}::{context or {}}"

    templates_mod.render_to_string = render_to_string


_install_django_stubs()
_install_canvas_sdk_stubs()


@pytest.fixture
def mock_staff():
    staff = MagicMock()
    staff.dbid = 101
    staff.id = "00000000-0000-0000-0000-000000000101"
    staff.first_name = "Alice"
    staff.last_name = "Chen"
    staff.active = True
    return staff


@pytest.fixture
def mock_nucc_code():
    code = MagicMock()
    code.code = "207R00000X"
    code.grouping = "Allopathic & Osteopathic Physicians"
    code.classification = "Internal Medicine"
    code.specialization = ""
    code.definition = "An internist..."
    code.display_name = "Internal Medicine"
    return code
