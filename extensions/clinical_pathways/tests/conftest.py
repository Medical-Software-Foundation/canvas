"""Shared test fixtures and Canvas-SDK / Django stubs.

The plugin depends on canvas_sdk and on Django. In the test environment neither is
available so we stub just enough of the surface area to let the plugin modules import
cleanly. Tests then mock behavior per-case rather than relying on real ORM / HTTP.
"""

from __future__ import annotations

import sys
import types

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
        "BooleanField",
        "DateTimeField",
        "JSONField",
        "CharField",
        "ForeignKey",
        "Index",
        "UniqueConstraint",
    ):
        setattr(django_db_models, cls, type(cls, (_FieldStub,), {}))

    setattr(django_db_models, "DO_NOTHING", object())
    setattr(django_db_models, "CASCADE", object())

    class TextChoices:
        @classmethod
        def choices(cls):
            return []

    setattr(django_db_models, "TextChoices", TextChoices)


def _install_canvas_sdk_stubs() -> None:
    canvas_sdk = _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    _ensure_module("canvas_sdk.v1.data")
    base = _ensure_module("canvas_sdk.v1.data.base")

    class CustomModel:
        pass

    setattr(base, "CustomModel", CustomModel)


@pytest.fixture(autouse=True)
def _stub_external_dependencies() -> None:
    _install_django_stubs()
    _install_canvas_sdk_stubs()
