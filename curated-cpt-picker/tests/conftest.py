"""Test setup that creates the CuratedCptCode custom-data table.

In production, Canvas creates CustomModel tables when the plugin installs.
In tests, we use Django's schema editor to make the table available against
the sqlite test database that pytest-django sets up.
"""

import pytest
from django.db import connection

from curated_cpt_picker.models.curated_cpt_code import CuratedCptCode


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):  # type: ignore[no-redef]
    """Create the CuratedCptCode table after pytest-django sets up the SDK tables."""
    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            existing_tables = connection.introspection.table_names()
            if CuratedCptCode._meta.db_table not in existing_tables:
                editor.create_model(CuratedCptCode)
