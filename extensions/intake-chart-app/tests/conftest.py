"""Shared pytest fixtures for the intake_chart_app test suite."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest


class _FakeAttributeQuerySet:
    """Stand-in for the QuerySet returned by hub.custom_attributes.filter(...).

    Supports the .delete() chaining the form_state clear-paths use.
    """

    def __init__(self, hub: "_FakeAttributeHub", name: str) -> None:
        self._hub = hub
        self._name = name

    def delete(self) -> None:
        self._hub._attrs.pop(self._name, None)


class _FakeAttribute:
    """Stand-in for the attribute rows exposed by
    ``hub.custom_attributes.all()``. The real SDK yields objects with
    ``.name`` and ``.value`` attributes; reproducing that shape lets us
    drive both ``FormStateSnapshot`` and ``get_all_section_drafts``
    through the same fake."""

    def __init__(self, name: str, value: Any) -> None:
        self.name = name
        self.value = value


class _FakeAttributeManager:
    def __init__(self, hub: "_FakeAttributeHub") -> None:
        self._hub = hub

    def filter(self, name: str) -> _FakeAttributeQuerySet:
        return _FakeAttributeQuerySet(self._hub, name)

    def all(self) -> list[Any]:
        return [
            _FakeAttribute(name, value)
            for name, value in self._hub._attrs.items()
        ]


class _FakeAttributeHub:
    def __init__(self, type_: str, id_: str) -> None:
        self.type = type_
        self.id = id_
        self._attrs: dict[str, Any] = {}
        self.custom_attributes = _FakeAttributeManager(self)

    def get_attribute(self, name: str) -> Any:
        return self._attrs.get(name)

    def set_attribute(self, name: str, value: Any) -> None:
        self._attrs[name] = value


class _FakeHubManager:
    """Replacement for AttributeHub.objects in tests."""

    def __init__(self) -> None:
        self._hubs: dict[tuple[str, str], _FakeAttributeHub] = {}

    def get_or_create(
        self, *, type: str, id: str
    ) -> tuple[_FakeAttributeHub, bool]:
        key = (type, id)
        if key in self._hubs:
            return self._hubs[key], False
        hub = _FakeAttributeHub(type, id)
        self._hubs[key] = hub
        return hub, True

    def filter(self, *, type: str, id: str) -> "_FakeHubFilter":
        return _FakeHubFilter(self._hubs.get((type, id)))


class _FakeHubFilter:
    def __init__(self, hub: _FakeAttributeHub | None) -> None:
        self._hub = hub

    def first(self) -> _FakeAttributeHub | None:
        return self._hub


@pytest.fixture
def fake_hubs(monkeypatch):
    """In-memory AttributeHub replacement.

    Patches ``intake_chart_app.data.form_state.AttributeHub`` to a fake whose
    ``.objects`` property is a per-test ``_FakeHubManager``. Returns the
    manager so tests can introspect what was written.
    """
    manager = _FakeHubManager()

    class _FakeAttributeHubClass:
        objects = manager

    monkeypatch.setattr(
        "intake_chart_app.data.form_state.AttributeHub",
        _FakeAttributeHubClass,
    )
    return manager


@pytest.fixture
def note_uuid() -> str:
    return str(uuid4())


@pytest.fixture
def patient_id() -> str:
    return str(uuid4())
