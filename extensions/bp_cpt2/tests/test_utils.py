# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from datetime import datetime, timezone

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Observation

from bp_cpt2.utils import get_blood_pressure_readings


def test_get_blood_pressure_readings_by_patient() -> None:
    """
    Test that get_blood_pressure_readings retrieves BP readings by patient.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create BP observation
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='140/90',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Get BP readings by patient
    systolic, diastolic = get_blood_pressure_readings(patient=patient)

    assert systolic == 140.0
    assert diastolic == 90.0


def test_get_blood_pressure_readings_by_note() -> None:
    """
    Test that get_blood_pressure_readings retrieves BP readings by note.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create BP observation
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='120/80',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Get BP readings by note
    systolic, diastolic = get_blood_pressure_readings(note=note)

    assert systolic == 120.0
    assert diastolic == 80.0


def test_get_blood_pressure_readings_no_bp_found() -> None:
    """
    Test that get_blood_pressure_readings returns None when no BP is found.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Get BP readings (no observations exist)
    systolic, diastolic = get_blood_pressure_readings(patient=patient)

    assert systolic is None
    assert diastolic is None


def test_get_blood_pressure_readings_invalid_format() -> None:
    """
    Test that get_blood_pressure_readings handles invalid BP format.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create BP observation with invalid format
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='invalid',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Get BP readings
    systolic, diastolic = get_blood_pressure_readings(patient=patient)

    assert systolic is None
    assert diastolic is None


def test_get_blood_pressure_readings_note_precedence() -> None:
    """
    Test that note parameter takes precedence when both patient and note are provided.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create two notes
    note1 = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    note2 = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create BP observations for both notes
    Observation.objects.create(
        patient=patient,
        note_id=note1.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='140/90',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    Observation.objects.create(
        patient=patient,
        note_id=note2.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='160/100',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Get BP readings passing both patient and note2
    # Should return note2's reading (160/100), not the most recent patient reading
    systolic, diastolic = get_blood_pressure_readings(patient=patient, note=note2)

    assert systolic == 160.0
    assert diastolic == 100.0


def test_get_blood_pressure_readings_requires_patient_or_note() -> None:
    """
    Test that get_blood_pressure_readings raises ValueError when neither patient nor note provided.
    """
    with pytest.raises(ValueError, match="Either patient or note must be provided"):
        get_blood_pressure_readings()


def test_get_blood_pressure_readings_most_recent() -> None:
    """
    Test that get_blood_pressure_readings returns the most recent BP reading.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create multiple BP observations (older first)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='120/80',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 1, tzinfo=timezone.utc)
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='150/95',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 2, tzinfo=timezone.utc)
    )

    # Get BP readings (should return most recent: 150/95)
    systolic, diastolic = get_blood_pressure_readings(patient=patient)

    assert systolic == 150.0
    assert diastolic == 95.0


def test_get_blood_pressure_readings_excludes_deleted() -> None:
    """
    Test that get_blood_pressure_readings excludes deleted observations.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create a deleted BP observation
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='140/90',
        units='mmHg',
        committer_id=1,
        deleted=True,  # Deleted
        effective_datetime=datetime.now(timezone.utc)
    )

    # Get BP readings (should return None since observation is deleted)
    systolic, diastolic = get_blood_pressure_readings(patient=patient)

    assert systolic is None
    assert diastolic is None
