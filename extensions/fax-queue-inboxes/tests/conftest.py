"""Shared fixtures for the whole suite.

The one fixture every test file touching the plugin's own custom data needs is here
rather than copied into each file, since pytest already hands an autouse session
fixture to every test in the run with no import required.
"""

import pytest
from django.db import connection
from pytest_django import DjangoDbBlocker

from fax_queue_inboxes.models import FaxLabel, FaxRecord, PracticeLabel


@pytest.fixture(scope="session", autouse=True)
def _fax_queue_custom_model_tables(
    django_db_setup: None, django_db_blocker: DjangoDbBlocker
) -> None:
    """Create a table for PracticeLabel, FaxRecord and FaxLabel.

    All three are managed by Django but ship no migration files, since on a real instance
    the platform creates their tables when the namespace is installed. Without this every
    test touching any of them fails on a missing table rather than on anything the plugin
    did.
    """
    with django_db_blocker.unblock():
        existing = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in (PracticeLabel, FaxRecord, FaxLabel):
                if model._meta.db_table not in existing:
                    editor.create_model(model)
