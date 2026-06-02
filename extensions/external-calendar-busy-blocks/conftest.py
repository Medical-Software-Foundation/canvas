"""Test configuration for external_calendar_busy_blocks.

The SDK's test infrastructure (pytest-canvas) imports canvas_sdk before
conftest.py is loaded, which means django.setup() runs with the original
INSTALLED_APPS before we can register the plugin app. As a result, Django's
test runner does not create the plugin's CustomModel tables. We create
them explicitly via a session-scoped autouse fixture that runs after
the standard django_db_setup.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _create_plugin_tables(django_db_setup, django_db_blocker):
    from django.db import connections

    from external_calendar_busy_blocks.data.models import (
        ImportedEvent,
        StaffCalendarFeed,
    )

    with django_db_blocker.unblock():
        with connections["default"].schema_editor() as editor:
            editor.create_model(StaffCalendarFeed)
            editor.create_model(ImportedEvent)
