"""Test configuration for external_calendar_busy_blocks.

The SDK's test infrastructure (pytest-canvas) imports canvas_sdk before
conftest.py is loaded, which means django.setup() runs with the original
INSTALLED_APPS before we can register the plugin app.

This conftest overrides django_db_setup to manually create tables for the
two CustomModels after the test database is created.
"""

import pytest


@pytest.fixture(scope="session")
def django_db_setup(
    request: pytest.FixtureRequest,
    django_test_environment: None,
    django_db_blocker,
    django_db_use_migrations: bool,
    django_db_keepdb: bool,
    django_db_createdb: bool,
    django_db_modify_db_settings: None,
) -> None:
    """Create the test database and then create plugin model tables manually.

    The plugin app is not in INSTALLED_APPS (since django.setup() was called
    before our conftest loaded), so Django's syncdb won't create our tables.
    We create them explicitly after the test database is initialized.
    """
    from django.test.utils import setup_databases, teardown_databases

    if not django_db_use_migrations:
        from pytest_django.fixtures import _disable_migrations

        _disable_migrations()

    setup_db_args: dict = {}
    if django_db_keepdb and not django_db_createdb:
        setup_db_args["keepdb"] = True

    from pytest_django.fixtures import _get_databases_for_setup

    aliases, serialized_aliases = _get_databases_for_setup(request.session.items)

    with django_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            aliases=aliases,
            serialized_aliases=serialized_aliases,
            **setup_db_args,
        )

        # Manually create plugin model tables that syncdb skipped
        from django.db import connections

        from external_calendar_busy_blocks.data.models import (
            ImportedEvent,
            StaffCalendarFeed,
        )

        conn = connections["default"]
        with conn.schema_editor() as editor:
            editor.create_model(StaffCalendarFeed)
            editor.create_model(ImportedEvent)

    yield

    if not django_db_keepdb:
        with django_db_blocker.unblock():
            try:
                teardown_databases(db_cfg, verbosity=request.config.option.verbose)
            except Exception as exc:
                request.node.warn(
                    pytest.PytestWarning(
                        f"Error when trying to teardown test databases: {exc!r}"
                    )
                )
