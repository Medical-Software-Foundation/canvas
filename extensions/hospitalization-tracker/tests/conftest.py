"""Shared fixtures and factories for hospitalization-tracker tests."""
from __future__ import annotations

import factory
import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import Patient

from hospitalization_tracker.models import Hospitalization


class HospitalizationFactory(factory.django.DjangoModelFactory[Hospitalization]):
    """Factory for Hospitalization custom model instances."""

    class Meta:
        model = Hospitalization

    patient = factory.SubFactory(PatientFactory)  # type: ignore[no-untyped-call]
    admission_date = factory.Sequence(lambda n: f"2024-0{(n % 9) + 1}-15")  # type: ignore[no-untyped-call]
    discharge_date = factory.Sequence(lambda n: f"2024-0{(n % 9) + 1}-20")  # type: ignore[no-untyped-call]
    hospital_name = factory.Sequence(lambda n: f"General Hospital {n + 1}")  # type: ignore[no-untyped-call]
    reason_for_admission = factory.Sequence(lambda n: f"Chest pain episode {n + 1}")  # type: ignore[no-untyped-call]
    principal_diagnosis = "Acute MI"
    icu_stay = False
    icu_duration_days = None
    discharge_disposition = "Home"
    readmission_within_30_days = False
    treating_physician = "Dr. Smith"
    notes = ""


@pytest.fixture(scope="session", autouse=True)
def create_hospitalization_table(
    django_db_setup: None,
    django_db_blocker: pytest.FixtureRequest,
) -> None:
    """Create the Hospitalization table in the SQLite test database.

    The Canvas SDK custom model tables are not created by Django migrations in the
    test environment. We must create them manually using Django's schema editor.
    """
    from django.conf import settings
    from django.db import connection

    if "sqlite3" not in settings.DATABASES["default"]["ENGINE"]:
        return

    # Import to ensure the model class is loaded and use it directly
    from hospitalization_tracker.models.hospitalization import Hospitalization as HospModel

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        existing_tables = connection.introspection.table_names()
        if "hospitalization" not in existing_tables:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(HospModel)


@pytest.fixture
def patient() -> Patient:
    """Create a Patient instance for tests."""
    return PatientFactory.create()


@pytest.fixture
def hospitalization(patient: Patient) -> Hospitalization:
    """Create a Hospitalization instance linked to a patient."""
    return HospitalizationFactory.create(patient=patient)
