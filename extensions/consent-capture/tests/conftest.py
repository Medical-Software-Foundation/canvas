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
        PAGE = "page"
        NEW_WINDOW = "new_window"
        RIGHT_CHART_PANE = "right_chart_pane"
        RIGHT_CHART_PANE_LARGE = "right_chart_pane_large"

    def __init__(self, target=None, content=None, url=None, title=None):
        self.target = target
        self.content = content
        self.url = url
        self.title = title

    def apply(self):
        return {
            "type": "LaunchModalEffect",
            "target": self.target,
            "content": self.content,
            "url": self.url,
        }


_launch_modal.LaunchModalEffect = LaunchModalEffect
_effects.launch_modal = _launch_modal

_banner = _module("canvas_sdk.effects.banner_alert")


class AddBannerAlert:
    class Placement:
        CHART = "chart"
        TIMELINE = "timeline"
        APPOINTMENT_CARD = "appointment_card"
        SCHEDULING_CARD = "scheduling_card"
        PROFILE = "profile"

    class Intent:
        INFO = "info"
        WARNING = "warning"
        ALERT = "alert"

    def __init__(self, patient_id=None, key=None, narrative=None, placement=None,
                 intent=None, href=None, patient_filter=None):
        self.patient_id = patient_id
        self.key = key
        self.narrative = narrative
        self.placement = placement
        self.intent = intent
        self.href = href
        self.patient_filter = patient_filter

    def apply(self):
        return {
            "type": "AddBannerAlert", "patient_id": self.patient_id, "key": self.key,
            "narrative": self.narrative, "placement": self.placement,
            "intent": self.intent, "href": self.href, "patient_filter": self.patient_filter,
        }


class RemoveBannerAlert:
    def __init__(self, key=None, patient_id=None):
        self.key = key
        self.patient_id = patient_id

    def apply(self):
        return {"type": "RemoveBannerAlert", "key": self.key, "patient_id": self.patient_id}


_banner.AddBannerAlert = AddBannerAlert
_banner.RemoveBannerAlert = RemoveBannerAlert
_effects.banner_alert = _banner

_effects_action_button = _module("canvas_sdk.effects.action_button")


class ReloadPatientActionButtonsEffect:
    def __init__(self, id=None):
        self.id = id

    def apply(self):
        return {"type": "ReloadPatientActionButtonsEffect", "patient_id": self.id}


_effects_action_button.ReloadPatientActionButtonsEffect = ReloadPatientActionButtonsEffect
_effects.action_button = _effects_action_button

_simple_api_effects = _module("canvas_sdk.effects.simple_api")


class Response:
    pass


class JSONResponse:
    def __init__(self, content=None, status_code=None):
        self.content = content
        self.status_code = status_code


class HTMLResponse:
    def __init__(self, content=None, status_code=None, headers=None):
        self.content = content
        self.status_code = status_code


_simple_api_effects.Response = Response
_simple_api_effects.JSONResponse = JSONResponse
_simple_api_effects.HTMLResponse = HTMLResponse
_effects.simple_api = _simple_api_effects

_handlers = _module("canvas_sdk.handlers")
_canvas_sdk.handlers = _handlers


class BaseHandler:
    def __init__(self, *args, **kwargs):
        pass


_handlers.BaseHandler = BaseHandler

# canvas_sdk.events.EventType — a protobuf enum in the runtime. The stub exposes
# the event names the plugin listens for and a Name() that echoes the value.
_events = _module("canvas_sdk.events")


class EventType:
    CONSENT_CREATED = "CONSENT_CREATED"
    CONSENT_UPDATED = "CONSENT_UPDATED"
    CONSENT_DELETED = "CONSENT_DELETED"
    PATIENT_CREATED = "PATIENT_CREATED"
    PATIENT_UPDATED = "PATIENT_UPDATED"

    @staticmethod
    def Name(value):
        return value


_events.EventType = EventType
_canvas_sdk.events = _events

_action_button = _module("canvas_sdk.handlers.action_button")


class ActionButton:
    class ButtonLocation:
        CHART_PATIENT_HEADER = "chart_patient_header"

    def __init__(self, *args, **kwargs):
        pass


_action_button.ActionButton = ActionButton
_handlers.action_button = _action_button

_application = _module("canvas_sdk.handlers.application")


class Application:
    def __init__(self, *args, **kwargs):
        pass


_application.Application = Application
_handlers.application = _application

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


class PatientConsentCoding:
    objects = None


class BannerAlert:
    objects = None


_data.Patient = Patient
_data.PatientConsent = PatientConsent
_data.Staff = Staff
_data.PatientConsentCoding = PatientConsentCoding
_data.BannerAlert = BannerAlert
_v1.data = _data

_clients = _module("canvas_sdk.clients")
_canvas_sdk.clients = _clients
_canvas_fhir = _module("canvas_sdk.clients.canvas_fhir")


class CanvasFhir:
    def __init__(self, *args, **kwargs):
        self._base_url = "https://fhir.example"

    def create(self, *args, **kwargs):
        return {}

    def _get_headers(self):
        return {}


_canvas_fhir.CanvasFhir = CanvasFhir
_clients.canvas_fhir = _canvas_fhir

# canvas_sdk.utils.http.Http (used for direct FHIR GET/POST).
_utils = _module("canvas_sdk.utils")
_canvas_sdk.utils = _utils
_utils_http = _module("canvas_sdk.utils.http")


class Http:
    def get(self, *args, **kwargs):
        raise NotImplementedError

    def post(self, *args, **kwargs):
        raise NotImplementedError


_utils_http.Http = Http
_utils.http = _utils_http


# canvas_sdk.v1.data.base.CustomModel — the base for plugin-owned tables. Real
# ORM behavior is not needed in unit tests; tests patch the model's ``objects``.
_data_base = _module("canvas_sdk.v1.data.base")


class CustomModel:
    objects = None


_data_base.CustomModel = CustomModel
_data.base = _data_base


# Minimal django.db.models stubs so models.py imports without a real Django.
_django = _module("django")
_django_db = _module("django.db")
_django_models = _module("django.db.models")


def _field(*args, **kwargs):
    return None


class _Constraint:
    def __init__(self, *args, **kwargs):
        pass


_django_models.BooleanField = _field
_django_models.DateField = _field
_django_models.DateTimeField = _field
_django_models.DecimalField = _field
_django_models.IntegerField = _field
_django_models.JSONField = _field
_django_models.TextField = _field
_django_models.ForeignKey = _field
_django_models.OneToOneField = _field
_django_models.Index = _Constraint
_django_models.UniqueConstraint = _Constraint
_django.db = _django_db
_django_db.models = _django_models
