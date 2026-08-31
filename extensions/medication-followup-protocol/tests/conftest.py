"""Test setup shared by the whole suite.

The custom models are managed by Django but ship no migration files, because on a real
instance the platform creates their tables when the namespace is installed. The published
pytest-canvas does not create them either, so the suite creates them here through Django's
own schema editor. Without this every test touching a custom model fails on a missing
table rather than on anything the plugin did.
"""

import datetime
import json

import pytest
from django.db import connection

from medication_followup_protocol.models import (
    EnrolledStep,
    Enrollment,
    MedicationClass,
    MedicationClassCoverage,
    ProgramDefaults,
    ProgramStep,
)

#: Creation order matters, a table carrying a foreign key comes after its target.
CUSTOM_MODELS = [
    MedicationClass,
    MedicationClassCoverage,
    ProgramStep,
    Enrollment,
    EnrolledStep,
    ProgramDefaults,
]


@pytest.fixture(scope="session", autouse=True)
def create_custom_model_tables(django_db_setup: None, django_db_blocker: pytest.FixtureRequest) -> None:
    """Create a table for every custom model in the test database."""
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        existing = set(connection.introspection.table_names())
        with connection.schema_editor() as editor:
            for model in CUSTOM_MODELS:
                if model._meta.db_table not in existing:
                    editor.create_model(model)


@pytest.fixture
def medication_class() -> MedicationClass:
    """A medication class with nothing on it yet."""
    return MedicationClass.objects.create(
        name="GLP-1",
        description="Weekly GLP-1 agonist",
        active=True,
        recheck_note_type_id="3f7b2c1e-8a4d-4e51-9c26-0b5d7a9e1f34",
    )


def make_event(event_type: str, target: str = "", context: dict | None = None):
    """A real Event, built the way the platform builds one, for driving a handler."""
    from canvas_generated.messages.events_pb2 import Event as EventRequest
    from canvas_generated.messages.events_pb2 import EventType
    from canvas_sdk.events import Event

    return Event(
        EventRequest(
            type=EventType.Value(event_type),
            target=target,
            context=json.dumps(context or {}),
        )
    )


@pytest.fixture
def patient():
    """An active, living patient."""
    from canvas_sdk.test_utils.factories import PatientFactory

    return PatientFactory(active=True, deceased=False)


@pytest.fixture
def staff():
    """An active staff member, the one messages come from."""
    from canvas_sdk.test_utils.factories import StaffFactory

    return StaffFactory(active=True)


@pytest.fixture
def enrolment(medication_class, patient, staff):
    """An active enrolment on a class carrying no steps yet."""
    from medication_followup_protocol.models import Enrollment

    return Enrollment.objects.create(
        patient_id=patient.dbid,
        medication_class=medication_class,
        medication_label="semaglutide",
        sender_staff_id=staff.dbid,
        prescriber_staff_id=staff.dbid,
        start_date=datetime.date(2026, 8, 1),
        recheck_note_type_id=medication_class.recheck_note_type_id,
    )


@pytest.fixture
def add_step(medication_class, enrolment):
    """Put a step on the class and schedule it on the enrolment."""
    from medication_followup_protocol.models import EnrolledStep, ProgramStep, StepKind

    def _add(kind=StepKind.MESSAGE, day_offset=0, due_date=None, condition=None, **content):
        program_step = ProgramStep.objects.create(
            medication_class=medication_class,
            sequence=content.pop("sequence", 0),
            day_offset=day_offset,
            kind=kind,
            condition=condition,
            **content,
        )
        return EnrolledStep.objects.create(
            enrollment=enrolment,
            program_step=program_step,
            sequence=program_step.sequence,
            day_offset=day_offset,
            kind=kind,
            condition=condition,
            due_date=due_date or (enrolment.start_date + datetime.timedelta(days=day_offset)),
        )

    return _add


def make(model, **given):
    """Create a platform row, filling any required column the test did not name.

    The SDK models mirror production tables, so many columns are NOT NULL with no Django
    default. A test only cares about three or four of them, and spelling out the rest
    buries what the test is actually asserting.
    """
    from django.db import models as django_models

    blanks = {
        django_models.CharField: "",
        django_models.TextField: "",
        django_models.BooleanField: False,
        django_models.IntegerField: 0,
        django_models.BigIntegerField: 0,
        django_models.FloatField: 0.0,
        django_models.DecimalField: 0,
        django_models.DurationField: datetime.timedelta(0),
    }

    values = dict(given)
    for field in model._meta.fields:
        if field.primary_key or field.name in values or field.attname in values:
            continue
        if field.null or field.has_default() or getattr(field, "auto_now_add", False):
            continue
        if isinstance(field, django_models.ForeignKey):
            continue
        for field_type, blank in blanks.items():
            if isinstance(field, field_type):
                values[field.name] = blank
                break

    return model.objects.create(**values)
