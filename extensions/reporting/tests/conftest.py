"""Shared test fixtures and Django/Canvas-SDK stubs.

canvas_sdk and Django are not installed in the test env. We stub just enough of
the surface area to let plugin modules import cleanly, then mock behavior per case.
"""

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


def _install_django_stubs() -> None:
    _ensure_module("django")
    django_db = _ensure_module("django.db")
    m = _ensure_module("django.db.models")

    class Q:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.children = [("AND", list(kwargs.items()))]

        def __or__(self, other):
            combined = Q()
            combined.children = [("OR", [self, other])]
            return combined

        def __and__(self, other):
            combined = Q()
            combined.children = [("AND", [self, other])]
            return combined

    class _Expr:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    m.Q = Q
    for name in ("Count", "Case", "When", "Value", "F"):
        setattr(m, name, type(name, (_Expr,), {}))
    sys.modules["django.db"] = django_db
    sys.modules["django.db.models"] = m


def _install_canvas_sdk_stubs() -> None:
    _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    data = _ensure_module("canvas_sdk.v1.data")
    appt_mod = _ensure_module("canvas_sdk.v1.data.appointment")
    effects_mod = _ensure_module("canvas_sdk.effects")
    launch_modal_mod = _ensure_module("canvas_sdk.effects.launch_modal")
    simple_api_effects = _ensure_module("canvas_sdk.effects.simple_api")
    _ensure_module("canvas_sdk.handlers")
    app_mod = _ensure_module("canvas_sdk.handlers.application")
    simple_api_mod = _ensure_module("canvas_sdk.handlers.simple_api")
    templates_mod = _ensure_module("canvas_sdk.templates")

    class Effect:
        pass

    effects_mod.Effect = Effect

    class _Applied:
        def __init__(self, owner):
            self.owner = owner

    class LaunchModalEffect:
        class TargetType:
            DEFAULT_MODAL = "default_modal"
            NEW_WINDOW = "new_window"
            RIGHT_CHART_PANE = "right_chart_pane"
            RIGHT_CHART_PANE_LARGE = "right_chart_pane_large"
            PAGE = "page"
            NOTE = "note"

        def __init__(self, url=None, content=None, target=None, title="Untitled"):
            self.url = url
            self.content = content
            self.target = target
            self.title = title

        def apply(self):
            return _Applied(self)

    launch_modal_mod.LaunchModalEffect = LaunchModalEffect

    class Response:
        def __init__(self, content=None, status_code=200, headers=None, content_type=None):
            self.content = content
            self.status_code = status_code
            self.headers = headers or {}
            self.content_type = content_type

    class HTMLResponse(Response):
        def __init__(self, content="", status_code=200, headers=None):
            super().__init__(content, status_code, headers, "text/html")

    class JSONResponse(Response):
        def __init__(self, content=None, status_code=200, headers=None):
            super().__init__(content, status_code, headers, "application/json")
            self.data = content  # tests assert on resp.data

    simple_api_effects.Response = Response
    simple_api_effects.HTMLResponse = HTMLResponse
    simple_api_effects.JSONResponse = JSONResponse

    class Application:
        def __init__(self, *args, **kwargs):
            self.context = {}

    app_mod.Application = Application

    class SimpleAPI:
        def __init__(self, *args, **kwargs):
            pass

    class StaffSessionAuthMixin:
        pass

    class _Api:
        def _decorator(self, *a, **k):
            def wrap(fn):
                return fn
            return wrap

        get = post = patch = delete = _decorator

    simple_api_mod.SimpleAPI = SimpleAPI
    simple_api_mod.StaffSessionAuthMixin = StaffSessionAuthMixin
    simple_api_mod.api = _Api()

    templates_mod.render_to_string = lambda name, ctx=None: f"RENDERED:{name}"

    class _Status:
        completed = "completed"
        unconfirmed = "unconfirmed"
        confirmed = "confirmed"
        noshowed = "noshowed"
        cancelled = "cancelled"

    class AppointmentProgressStatus:
        UNCONFIRMED = "unconfirmed"
        ATTEMPTED = "attempted"
        CONFIRMED = "confirmed"
        ARRIVED = "arrived"
        ROOMED = "roomed"
        EXITED = "exited"
        NOSHOWED = "noshowed"
        CANCELLED = "cancelled"

    class Appointment:
        objects = MagicMock()

    appt_mod.Appointment = Appointment
    appt_mod.AppointmentProgressStatus = AppointmentProgressStatus
    data.Appointment = Appointment


_install_django_stubs()
_install_canvas_sdk_stubs()
