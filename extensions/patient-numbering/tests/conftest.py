"""Test setup: custom data tables in the SQLite test database, and a patient factory."""

import factory
import pytest

from canvas_sdk.test_utils.factories import PatientFactory
from patient_numbering.models import PatientProxy


class PatientProxyFactory(PatientFactory, factory.django.DjangoModelFactory[PatientProxy]):
    """Factory for PatientProxy."""

    class Meta:
        model = PatientProxy


def make_patient() -> PatientProxy:
    """Create and save a patient."""
    return PatientProxyFactory()  # type: ignore[no-untyped-call]


@pytest.fixture(scope="session", autouse=True)
def create_custom_tables(
    django_db_setup: None,
    django_db_blocker: pytest.FixtureRequest,
) -> None:
    """Custom model tables are not created by Django migrations in tests, so create them here."""
    from django.conf import settings
    from django.db import connection

    if "sqlite3" not in settings.DATABASES["default"]["ENGINE"]:
        return

    from patient_numbering.models import NumberingState, PatientNumber

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        existing = connection.introspection.table_names()
        with connection.schema_editor() as schema_editor:
            for model in (PatientNumber, NumberingState):
                if model._meta.db_table not in existing:
                    schema_editor.create_model(model)
