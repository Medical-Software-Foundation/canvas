"""Shared fixtures for order_sets tests.

Uses ``canvas[test-utils]`` (configured via DJANGO_SETTINGS_MODULE in
pyproject.toml). All external Canvas ORM access is patched on a per-test
basis with ``pytest-mock``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


# ── Staff & roles ─────────────────────────────────────────────────────────────

def make_staff(
    staff_id: str = "staff-1",
    first_name: str = "Alex",
    last_name: str = "Provider",
    active: bool = True,
    top_role_abbreviation: str = "MD",
) -> SimpleNamespace:
    """Mimic a Staff record (used by Staff.objects.filter().first())."""
    return SimpleNamespace(
        id=staff_id,
        first_name=first_name,
        last_name=last_name,
        active=active,
        top_role_abbreviation=top_role_abbreviation,
    )


def make_staff_role(
    staff: SimpleNamespace,
    role_type: str = "PROVIDER",
    name: str = "Provider",
    domain: str = "",
    internal_code: str = "",
) -> SimpleNamespace:
    """Mimic a StaffRole record."""
    return SimpleNamespace(
        staff=staff,
        role_type=role_type,
        name=name,
        domain=domain,
        internal_code=internal_code,
    )


# ── Notes ─────────────────────────────────────────────────────────────────────

def make_note(
    note_id: str = "note-1",
    dbid: int = 100,
    provider: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Mimic a Note record."""
    return SimpleNamespace(id=note_id, dbid=dbid, provider=provider)


# ── Lab partners & tests ──────────────────────────────────────────────────────

def make_lab_partner(
    partner_id: str = "lp-1",
    name: str = "LabCorp",
    electronic_ordering_enabled: bool = True,
    tests: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    """Mimic a LabPartner record with an `available_tests` related manager."""
    available_tests = _make_test_manager(tests or [])
    return SimpleNamespace(
        id=partner_id,
        name=name,
        electronic_ordering_enabled=electronic_ordering_enabled,
        available_tests=available_tests,
    )


def make_lab_test(
    order_code: str = "CBC",
    order_name: str = "Complete Blood Count",
    cpt_code: str = "85025",
) -> SimpleNamespace:
    return SimpleNamespace(
        order_code=order_code,
        order_name=order_name,
        cpt_code=cpt_code,
    )


def _make_test_manager(tests: list[SimpleNamespace]) -> MagicMock:
    """Build a manager whose `.all()` / `.filter()` / `.order_by()` / slicing
    behave like a Django QuerySet over ``tests``."""

    class _QS:
        def __init__(self, items: list[SimpleNamespace]) -> None:
            self._items = items

        def filter(self, **kwargs: Any) -> "_QS":
            search = kwargs.get("order_name__icontains", "").lower()
            if search:
                return _QS([t for t in self._items if search in t.order_name.lower()])
            return self

        def order_by(self, *_args: str) -> "_QS":
            return _QS(sorted(self._items, key=lambda t: t.order_name))

        def __getitem__(self, key: Any) -> list[SimpleNamespace]:
            return self._items[key]

        def __iter__(self) -> Any:
            return iter(self._items)

    qs = _QS(tests)
    manager = MagicMock()
    manager.all = lambda: qs
    return manager


# ── ChargeDescriptionMaster (CPT codes) ───────────────────────────────────────

def make_cdm(
    cpt_code: str = "82951",
    name: str = "Glucose tolerance test",
) -> SimpleNamespace:
    return SimpleNamespace(cpt_code=cpt_code, name=name)


# ── In-memory cache replacement ───────────────────────────────────────────────

class FakeCache:
    """Behaves like the Canvas plugin cache for the ops the plugin uses."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any, timeout_seconds: int = 0) -> None:
        self._store[key] = value

    def clear(self) -> None:
        self._store.clear()


@pytest.fixture
def fake_cache(mocker: Any) -> FakeCache:
    """Patch ``get_cache`` in endpoints.py to return a fresh in-memory cache."""
    cache = FakeCache()
    mocker.patch("order_sets.api.endpoints.get_cache", return_value=cache)
    return cache


# ── Request / API instance helpers ────────────────────────────────────────────

def make_request(
    *,
    json_body: dict[str, Any] | None = None,
    query_params: dict[str, str] | None = None,
    path: str = "",
    headers: dict[str, str] | None = None,
    body: bytes | str = b"",
) -> MagicMock:
    """Build a request object compatible with the SimpleAPI shape used here."""
    req = MagicMock()
    req.json = MagicMock(return_value=json_body if json_body is not None else {})
    req.query_params = query_params or {}
    req.path = path
    req.headers = headers or {}
    req.body = body
    return req


@pytest.fixture
def api_instance() -> Any:
    """Return an OrderSetsAPI instance with no __init__ side effects.

    SimpleAPI's __init__ requires runtime context we don't want to invoke. We
    instead create the instance via ``object.__new__`` and attach the
    attributes the methods read.
    """
    from order_sets.api.endpoints import OrderSetsAPI

    inst = object.__new__(OrderSetsAPI)
    inst.request = make_request()  # default: empty request
    inst.secrets = {}
    inst.environment = {}
    return inst
