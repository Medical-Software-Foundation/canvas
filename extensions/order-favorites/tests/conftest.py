"""Shared fixtures. The canvas test harness gives a real test database, so the rules are tested
against real rows. The plugin's own tables aren't made by migrations; they are created once here."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from canvas_sdk.v1.data.lab import LabPartner, LabPartnerTest

from order_favorites.handlers.api import OrderFavoritesAPI
from order_favorites.models import CustomStaff, Favorite, FavoritesAdmin, HiddenFavorite, PracticeSetting

PLUGIN_MODELS: list[Any] = [Favorite, HiddenFavorite, FavoritesAdmin, PracticeSetting]


@pytest.fixture(scope="session", autouse=True)
def _plugin_tables(django_db_setup: Any, django_db_blocker: Any) -> Iterator[None]:
    from django.db import connection

    with django_db_blocker.unblock():
        existing = connection.introspection.table_names()
        with connection.schema_editor() as editor:
            for model in PLUGIN_MODELS:
                if model._meta.db_table not in existing:
                    editor.create_model(model)
    yield


@pytest.fixture(autouse=True)
def _db(db: Any) -> None:
    """Every test gets the database."""


@pytest.fixture
def make_staff() -> Callable[..., CustomStaff]:
    from canvas_sdk.v1.data.staff import Staff
    from canvas_sdk.v1.data.user import CanvasUser

    language_model = Staff._meta.get_field("language").related_model

    def _make(first: str = "Pat", last: str = "Provider", npi: str = "", active: bool = True, email: str = "", key: str = "") -> CustomStaff:
        language = language_model.objects.create(code="en", description="English")
        user = CanvasUser.objects.create(email=email) if email else None
        extra = {"id": key} if key else {}
        staff: CustomStaff = CustomStaff.objects.create(first_name=first, last_name=last, npi_number=npi, active=active, language=language, user=user, **extra)
        return staff

    return _make


@pytest.fixture
def make_partner() -> Callable[..., LabPartner]:
    def _make(name: str = "Generic Lab", active: bool = True, tests: list[tuple[str, str]] | None = None) -> LabPartner:
        partner = LabPartner.objects.create(name=name, active=active, electronic_ordering_enabled=False)
        for code, test_name in tests or []:
            LabPartnerTest.objects.create(lab_partner=partner, order_code=code, order_name=test_name, cpt_code="")
        return partner

    return _make


@pytest.fixture
def make_note() -> Callable[..., Any]:
    """A note of a given category and current state."""
    from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteType

    def _make(category: str = "encounter", state: str = "NEW", provider: Any = None, title: str = "") -> Note:
        note_type = NoteType.objects.create(category=category, name=category.title(), is_active=True, is_visible=True, rank=1)
        note = Note.objects.create(note_type_version=note_type, provider=provider, title=title)
        CurrentNoteStateEvent.objects.create(note=note, state=state)
        return note

    return _make


def make_api(staff: Any = None, body: Any = None, path: dict[str, str] | None = None, query: dict[str, str] | None = None, secrets: dict[str, str] | None = None) -> OrderFavoritesAPI:
    handler = OrderFavoritesAPI.__new__(OrderFavoritesAPI)
    handler.secrets = secrets if secrets is not None else {}
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": str(staff.id)} if staff is not None else {}
    request.json.return_value = body if body is not None else {}
    request.path_params = path or {}
    request.query_params = query or {}
    handler.request = request
    return handler


def reply(results: list[Any]) -> tuple[int, dict[str, Any]]:
    resp = [r for r in results if hasattr(r, "status_code")][0]
    return resp.status_code, json.loads(resp.content)
