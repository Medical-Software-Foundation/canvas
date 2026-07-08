"""Shared test scaffolding for the consent_capture plugin.

Two things are set up before the plugin's modules can be imported in a plain
pytest process:

1. The plugin source lives in the inner ``consent_capture`` folder (a sibling of
   this ``tests/`` directory, not on ``sys.path`` by default). We register the
   ``consent_capture`` package pointing at that folder so intra-plugin imports
   resolve regardless of how pytest was invoked.

2. ``canvas_sdk`` and ``logger`` are provided by the Canvas runtime and are not
   installed locally. We inject lightweight stub modules so the handlers import
   cleanly; individual tests patch/replace the pieces they care about.
"""

import importlib.machinery
import importlib.util
import os
import sys
import types

import pytest

# --------------------------------------------------------------------------- #
# 1. Register the plugin source under its runtime package name.
# --------------------------------------------------------------------------- #
_CONTAINER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INNER = os.path.join(_CONTAINER, "consent_capture")

if "consent_capture" not in sys.modules:
    _spec = importlib.machinery.ModuleSpec("consent_capture", None, is_package=True)
    _spec.submodule_search_locations = [_INNER]
    sys.modules["consent_capture"] = importlib.util.module_from_spec(_spec)


# --------------------------------------------------------------------------- #
# 2. Stub the Canvas-runtime-provided modules.
# --------------------------------------------------------------------------- #
def _module(name):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# logger.log
_logger = _module("logger")


class _Log:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


_logger.log = _Log()


# canvas_sdk package tree
_canvas_sdk = _module("canvas_sdk")

_effects = _module("canvas_sdk.effects")


class Effect:
    pass


_effects.Effect = Effect
_canvas_sdk.effects = _effects

_launch_modal = _module("canvas_sdk.effects.launch_modal")


class LaunchModalEffect:
    class TargetType:
        DEFAULT_MODAL = "default_modal"

    def __init__(self, target=None, content=None):
        self.target = target
        self.content = content

    def apply(self):
        return {"type": "LaunchModalEffect", "target": self.target, "content": self.content}


_launch_modal.LaunchModalEffect = LaunchModalEffect
_effects.launch_modal = _launch_modal

_simple_api_effects = _module("canvas_sdk.effects.simple_api")


class Response:
    pass


class JSONResponse:
    def __init__(self, content=None, status_code=None):
        self.content = content
        self.status_code = status_code


_simple_api_effects.Response = Response
_simple_api_effects.JSONResponse = JSONResponse
_effects.simple_api = _simple_api_effects

_handlers = _module("canvas_sdk.handlers")
_canvas_sdk.handlers = _handlers

_action_button = _module("canvas_sdk.handlers.action_button")


class ActionButton:
    class ButtonLocation:
        CHART_PATIENT_HEADER = "chart_patient_header"

    def __init__(self, *args, **kwargs):
        pass


_action_button.ActionButton = ActionButton
_handlers.action_button = _action_button

_simple_api = _module("canvas_sdk.handlers.simple_api")


class SimpleAPI:
    def __init__(self, *args, **kwargs):
        pass


class StaffSessionAuthMixin:
    pass


class _ApiRouter:
    def post(self, path):
        def decorator(fn):
            return fn

        return decorator

    def get(self, path):
        def decorator(fn):
            return fn

        return decorator


_simple_api.SimpleAPI = SimpleAPI
_simple_api.StaffSessionAuthMixin = StaffSessionAuthMixin
_simple_api.api = _ApiRouter()
_handlers.simple_api = _simple_api

_templates = _module("canvas_sdk.templates")


def render_to_string(template_name, context):
    return ""


_templates.render_to_string = render_to_string
_canvas_sdk.templates = _templates

_v1 = _module("canvas_sdk.v1")
_canvas_sdk.v1 = _v1
_data = _module("canvas_sdk.v1.data")


class Patient:
    objects = None


class PatientConsent:
    objects = None


class Staff:
    objects = None


_data.Patient = Patient
_data.PatientConsent = PatientConsent
_data.Staff = Staff
_v1.data = _data

_clients = _module("canvas_sdk.clients")
_canvas_sdk.clients = _clients
_canvas_fhir = _module("canvas_sdk.clients.canvas_fhir")


class CanvasFhir:
    def __init__(self, *args, **kwargs):
        pass

    def create(self, *args, **kwargs):
        return {}


_canvas_fhir.CanvasFhir = CanvasFhir
_clients.canvas_fhir = _canvas_fhir
