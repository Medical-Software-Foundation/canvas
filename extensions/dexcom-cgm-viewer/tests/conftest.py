"""Test fixtures.

The Canvas SDK ships its own bundled Django settings whose ``INSTALLED_APPS``
is fixed to ``["django.contrib.contenttypes", "canvas_sdk.v1"]``. Plugin
custom data models therefore need to opt themselves into the test SQLite DB
schema explicitly — otherwise the metaclass marks them ``managed`` but
Django's ``migrate`` step never sees them.

This fixture runs once per session, after pytest-django has built the test
database, and uses Django's ``schema_editor`` to ``CREATE TABLE`` for each
plugin model. Tearing them down is unnecessary because pytest-django
destroys the SQLite file at session teardown.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from django.db import connection


@pytest.fixture(scope="session", autouse=True)
def _create_plugin_tables(django_db_setup: None, django_db_blocker: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Create the plugin's custom data tables once per test session."""
    # Import models lazily so canvas_sdk has already configured Django.
    from dexcom_cgm_viewer.models import (
        DexcomEgv,
        DexcomOAuthToken,
        DexcomSummary,
        DexcomSyncState,
    )

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with connection.schema_editor() as schema_editor:
            for model in (DexcomOAuthToken, DexcomSyncState, DexcomEgv, DexcomSummary):
                if model._meta.db_table not in connection.introspection.table_names():
                    schema_editor.create_model(model)
    yield
