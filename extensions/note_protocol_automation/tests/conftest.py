"""Shared test fixtures.

The plugin's ``Rule`` model is a ``CustomModel``: in production its table is
created by the plugin installer, and in SQLite it is ``managed`` but has no
Django migration files. The published ``canvas[test-utils]`` harness creates the
core SDK tables but not plugin custom-model tables, so a test that reads or
writes ``Rule`` would otherwise hit ``no such table: rule``.

This session-scoped fixture creates the ``Rule`` table once, after the test
database is built, using Django's own schema editor — no canvas-plugins repo or
``plugin_runner`` DDL helpers required, so it stays portable. The same ``Rule``
class the tests import is the one whose table is created, so there is no stale
model-registry reference.
"""

from collections.abc import Generator

import pytest
from django.db import connection
from pytest_django.plugin import DjangoDbBlocker


@pytest.fixture(scope="session", autouse=True)
def _create_rule_table(
    django_db_setup: None, django_db_blocker: DjangoDbBlocker
) -> Generator[None, None, None]:
    """Create the ``Rule`` custom-model table in the SQLite test database."""
    from note_protocol_automation.models.rule import Rule

    with django_db_blocker.unblock():
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(Rule)
    yield
