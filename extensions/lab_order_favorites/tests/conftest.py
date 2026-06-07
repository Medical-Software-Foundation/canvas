"""Shared fixtures for lab order favorites tests.

The canvas test harness (pytest_canvas + pytest-django) provides a real test
database, so model-backed logic is tested against real rows rather than mocked
queryset chains. Core models (Staff, LabPartner) need a couple of required
fields filled; these helpers keep that in one place.
"""

from typing import Any, Callable

import pytest
from canvas_sdk.v1.data.lab import LabPartner, LabPartnerTest

from lab_order_favorites.models import CustomStaff, LabFavorite


@pytest.fixture(scope="session", autouse=True)
def _custom_model_tables(django_db_setup, django_db_blocker):
    """Create the plugin's CustomModel tables once for the test session.

    Plugin custom-data models are not part of the test settings' INSTALLED_APPS,
    so their tables are not produced by migrations. Build them with the schema
    editor at session setup (outside the per-test transaction) so rows created
    in tests persist for the duration of each test and roll back afterward.
    """
    from django.db import connection

    with django_db_blocker.unblock():
        if LabFavorite._meta.db_table not in connection.introspection.table_names():
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(LabFavorite)
    yield


@pytest.fixture
def make_staff() -> Callable[..., CustomStaff]:
    """Return a factory that creates a Staff record with a minimal Language."""
    from canvas_sdk.v1.data.staff import Staff

    language_field = Staff._meta.get_field("language")
    language_model = language_field.related_model

    def _make(
        first_name: str = "Pat",
        last_name: str = "Provider",
        npi_number: str = "",
        active: bool = True,
    ) -> CustomStaff:
        language = language_model.objects.create(code="en", description="English")
        return CustomStaff.objects.create(
            first_name=first_name,
            last_name=last_name,
            npi_number=npi_number,
            active=active,
            language=language,
        )

    return _make


@pytest.fixture
def make_partner() -> Callable[..., LabPartner]:
    """Return a factory that creates a LabPartner with its tests."""

    def _make(
        name: str = "LabCorp",
        active: bool = True,
        tests: list[tuple[str, str]] | None = None,
    ) -> LabPartner:
        partner = LabPartner.objects.create(
            name=name, active=active, electronic_ordering_enabled=False
        )
        for order_code, order_name in tests or []:
            LabPartnerTest.objects.create(
                lab_partner=partner,
                order_code=order_code,
                order_name=order_name,
                cpt_code="",
            )
        return partner

    return _make


class FakeRequest:
    """Minimal stand-in for a SimpleAPI request object."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.headers = headers or {}
        self.query_params = query_params or {}
        self._body = body if body is not None else {}

    def json(self) -> dict[str, Any]:
        return self._body


@pytest.fixture
def make_request() -> Callable[..., FakeRequest]:
    """Return a factory for FakeRequest objects."""

    def _make(
        staff_id: str = "",
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> FakeRequest:
        headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
        return FakeRequest(headers=headers, query_params=query, body=body)

    return _make
