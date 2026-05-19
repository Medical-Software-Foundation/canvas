"""Mock all Canvas SDK + Django modules before any plugin code is imported.

Tests verify business logic without requiring a real Canvas instance or
Django app registry to be configured.
"""
import sys
from unittest.mock import MagicMock


def _passthrough_api():
    api = MagicMock()

    def _deco(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    api.get = _deco
    api.post = _deco
    api.put = _deco
    api.delete = _deco
    return api


class _Mixin:
    pass


class _SimpleAPI:
    pass


def _fake_response(*args, **kwargs):
    """Return a stand-in response object that records its args."""
    resp = MagicMock()
    resp._args = args
    resp._kwargs = kwargs
    resp.body = args[0] if args else None
    resp.status_code = kwargs.get("status_code")
    return resp


_simple_api_mod = MagicMock()
_simple_api_mod.api = _passthrough_api()
_simple_api_mod.StaffSessionAuthMixin = _Mixin
_simple_api_mod.SimpleAPI = _SimpleAPI
_simple_api_mod.JSONResponse = MagicMock(side_effect=_fake_response)
_simple_api_mod.HTMLResponse = MagicMock(side_effect=_fake_response)
_simple_api_mod.Response = MagicMock(side_effect=_fake_response)


class _LaunchModalEffect:
    class TargetType:
        RIGHT_CHART_PANE = "RIGHT_CHART_PANE"
        DEFAULT_MODAL = "DEFAULT_MODAL"
        PAGE = "PAGE"

    def __init__(self, url=None, content=None, target=None, title=None):
        self.url = url
        self.content = content
        self.target = target
        self.title = title

    def apply(self):
        return MagicMock(
            url=self.url,
            content=self.content,
            target=self.target,
            title=self.title,
        )


_launch_modal_mod = MagicMock()
_launch_modal_mod.LaunchModalEffect = _LaunchModalEffect


_templates_mod = MagicMock()
_templates_mod.render_to_string = MagicMock(return_value="<html>rendered</html>")


# Lab/Note/Staff/StaffRole models are mocked as MagicMock classes; their
# `.objects` attribute is reconfigured per-test.
def _stub_model_module():
    mod = MagicMock()
    return mod


_lab_mod = _stub_model_module()
_note_mod = _stub_model_module()


class _NoteStates:
    NEW = "NEW"
    PUSHED = "PUSHED"
    CONVERTED = "CONVERTED"
    UNLOCKED = "UNLOCKED"
    RESTORED = "RESTORED"
    UNDELETED = "UNDELETED"


_note_mod.NoteStates = _NoteStates


class _Staff:
    objects = MagicMock()


class _StaffRole:
    class RoleDomain:
        CLINICAL = "CLI"
        ADMINISTRATIVE = "ADM"
        HYBRID = "HYB"

    class RoleType:
        PROVIDER = "PROVIDER"
        LICENSED = "LICENSED"
        NON_LICENSED = "NON-LICENSED"

    objects = MagicMock()


_staff_mod = MagicMock()
_staff_mod.Staff = _Staff
_staff_mod.StaffRole = _StaffRole


# CustomModel base + OrderSet model: we substitute OrderSet with a plain
# class whose `objects` we can swap per-test.
class _CustomModel:
    pass


_base_mod = MagicMock()
_base_mod.CustomModel = _CustomModel


_charge_master_mod = MagicMock()


class _LabOrderCommand:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def originate(self):
        return MagicMock(_kind="lab", _kwargs=self.kwargs)


class _ImagingOrderCommand:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def originate(self):
        return MagicMock(_kind="imaging", _kwargs=self.kwargs)


class _PerformCommand:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def originate(self):
        return MagicMock(_kind="perform", _kwargs=self.kwargs)


_commands_mod = MagicMock()
_commands_mod.LabOrderCommand = _LabOrderCommand
_commands_mod.ImagingOrderCommand = _ImagingOrderCommand
_commands_mod.PerformCommand = _PerformCommand


_application_mod = MagicMock()


class _Application:
    pass


_application_mod.Application = _Application


_logger_mod = MagicMock()
_logger_mod.log = MagicMock()


# Register all mocks BEFORE the plugin code is imported anywhere.
_mocks = {
    "canvas_sdk": MagicMock(),
    "canvas_sdk.caching": MagicMock(),
    "canvas_sdk.caching.plugins": MagicMock(),
    "canvas_sdk.commands": _commands_mod,
    "canvas_sdk.effects": MagicMock(),
    "canvas_sdk.effects.simple_api": _simple_api_mod,
    "canvas_sdk.effects.launch_modal": _launch_modal_mod,
    "canvas_sdk.handlers": MagicMock(),
    "canvas_sdk.handlers.simple_api": _simple_api_mod,
    "canvas_sdk.handlers.application": _application_mod,
    "canvas_sdk.templates": _templates_mod,
    "canvas_sdk.v1": MagicMock(),
    "canvas_sdk.v1.data": MagicMock(),
    "canvas_sdk.v1.data.base": _base_mod,
    "canvas_sdk.v1.data.lab": _lab_mod,
    "canvas_sdk.v1.data.note": _note_mod,
    "canvas_sdk.v1.data.staff": _staff_mod,
    "canvas_sdk.v1.data.charge_description_master": _charge_master_mod,
    "logger": _logger_mod,
}

for _name, _mock in _mocks.items():
    sys.modules[_name] = _mock


# Stub django.db.models so the OrderSet model body imports cleanly.
_django_mod = MagicMock()
_django_db_mod = MagicMock()
_django_db_models_mod = MagicMock()
_django_db_models_mod.BooleanField = MagicMock
_django_db_models_mod.DateTimeField = MagicMock
_django_db_models_mod.JSONField = MagicMock
_django_db_models_mod.TextField = MagicMock
_django_db_models_mod.Index = MagicMock
_django_db_models_mod.UniqueConstraint = MagicMock


class _Q:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __or__(self, other):
        return _Q(_or=(self, other))

    def __and__(self, other):
        return _Q(_and=(self, other))


_django_db_models_mod.Q = _Q

sys.modules["django"] = _django_mod
sys.modules["django.db"] = _django_db_mod
sys.modules["django.db.models"] = _django_db_models_mod


# Pre-attach an `objects` manager attribute to the OrderSet class so that
# tests can monkeypatch.setattr it per-test. CustomModel's real manager is
# wired up by Django's app registry, which we don't initialize here.
def _attach_orderset_objects():
    from order_sets.models.order_set import OrderSet

    if not hasattr(OrderSet, "objects"):
        OrderSet.objects = MagicMock()


_attach_orderset_objects()
