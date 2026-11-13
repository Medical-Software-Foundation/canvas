import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from django.db import connection

# Make the plugin package importable when pytest runs from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def queue_table() -> Iterator[None]:
    """Create the plugin's custom data table in the test database (Canvas does this on install)."""
    from canvas__ondemand_provider_queue.models import QueueEntryRecord

    # The test run already holds a transaction, so build the CREATE TABLE
    # statement without entering the schema editor (SQLite refuses that here).
    sql, params = connection.schema_editor().table_sql(QueueEntryRecord)
    table = QueueEntryRecord._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
    yield
    with connection.cursor() as cursor:
        cursor.execute(f'DROP TABLE IF EXISTS "{table}"')
