# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Observation, Assessment

from bp_cpt2.bp_claim_coder import get_blood_pressure_readings, get_hypertension_related_assessments, process_bp_billing_for_note


def test_get_blood_pressure_readings_by_patient() -> None:
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
        value='140/90',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Get BP readings by note
    systolic, diastolic = get_blood_pressure_readings(note)

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
    systolic, diastolic = get_blood_pressure_readings(note)

    assert systolic == 120.0
    assert diastolic == 80.0


def test_get_blood_pressure_readings_no_bp_found() -> None:
    """
    Test that get_blood_pressure_readings returns None when no BP is found.
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

    # Get BP readings (no observations exist)
    systolic, diastolic = get_blood_pressure_readings(note)

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
    systolic, diastolic = get_blood_pressure_readings(note)

    assert systolic is None
    assert diastolic is None


def test_get_blood_pressure_readings_requires_note() -> None:
    """
    Test that get_blood_pressure_readings requires note parameter.
    """
    with pytest.raises(TypeError, match="missing 1 required positional argument: 'note'"):
        get_blood_pressure_readings()


def test_get_blood_pressure_readings_most_recent() -> None:
    """
    Test that get_blood_pressure_readings returns the minimum BP values from multiple readings.
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

    # Get BP readings (should return minimum: 120/80)
    systolic, diastolic = get_blood_pressure_readings(note)

    assert systolic == 120.0
    assert diastolic == 80.0


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
    systolic, diastolic = get_blood_pressure_readings(note)

    assert systolic is None
    assert diastolic is None


def test_get_blood_pressure_readings_minimum_from_three() -> None:
    """
    Test that get_blood_pressure_readings returns minimum values from up to 3 most recent observations.
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

    # Create 4 BP observations - the oldest should be ignored (only 3 most recent used)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='100/60',  # This is oldest and should be IGNORED
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
        value='130/85',  # 2nd oldest - included in 3 most recent
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 2, tzinfo=timezone.utc)
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='145/90',  # 2nd newest
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 3, tzinfo=timezone.utc)
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='135/95',  # Most recent
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 4, tzinfo=timezone.utc)
    )

    # Get BP readings - should use 3 most recent (130/85, 145/90, 135/95)
    # Minimum systolic: 130, Minimum diastolic: 85
    systolic, diastolic = get_blood_pressure_readings(note)

    assert systolic == 130.0
    assert diastolic == 85.0


def test_get_hypertension_related_assessments_no_assessments() -> None:
    """
    Test get_hypertension_related_assessments when note has no assessments.
    Covers early return path (line 309).
    """
    # Create test patient and note (no assessments)
    patient = PatientFactory.create()
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Call function - should return empty list without calling LLM
    result = get_hypertension_related_assessments(note, "test-api-key")
    assert result == []


def test_get_hypertension_related_assessments_assessments_without_conditions() -> None:
    """
    Test get_hypertension_related_assessments when assessments have no conditions.
    Covers the path where assessments exist but have no conditions (line 314-315, 338-339).
    """
    # Create test patient and note
    patient = PatientFactory.create()
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create assessments WITHOUT conditions
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Call function - should return empty list because assessments have no conditions
    result = get_hypertension_related_assessments(note, "test-api-key")
    assert result == []


def test_get_hypertension_related_assessments_no_api_key() -> None:
    """
    Test get_hypertension_related_assessments without API key.
    Covers lines 343-345 (missing API key path).
    """
    # Create test patient and note
    patient = PatientFactory.create()
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Call function without API key
    result = get_hypertension_related_assessments(note, None)

    # Should return empty list
    assert result == []

    # Also test with empty string
    result = get_hypertension_related_assessments(note, "")
    assert result == []


def test_process_bp_billing_cache_hit() -> None:
    """
    Test that process_bp_billing_for_note skips processing when cache key exists.
    Covers lines 425-427 (cache hit path).
    """
    # Create test patient and note
    patient = PatientFactory.create()
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
        value='150/100',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Mock cache to return that key already exists
    mock_cache = Mock()
    mock_cache.__contains__ = Mock(return_value=True)  # Key exists in cache

    with patch('bp_cpt2.bp_claim_coder.get_cache', return_value=mock_cache):
        # Call with was_just_locked=True to trigger cache check
        result = process_bp_billing_for_note(
            note=note,
            openai_api_key="test-key",
            include_treatment_codes=False,
            was_just_locked=True
        )

        # Should return empty list due to cache hit
        assert result == []


def test_process_bp_billing_cache_miss_sets_key() -> None:
    """
    Test that process_bp_billing_for_note sets cache key on miss.
    Covers lines 429-431 (cache miss, set key path).
    """
    # Create test patient and note
    patient = PatientFactory.create()
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
        value='150/100',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Mock cache to return that key doesn't exist
    mock_cache = Mock()
    mock_cache.__contains__ = Mock(return_value=False)  # Key doesn't exist
    mock_cache.set = Mock()

    with patch('bp_cpt2.bp_claim_coder.get_cache', return_value=mock_cache):
        # Call with was_just_locked=True to trigger cache check
        result = process_bp_billing_for_note(
            note=note,
            openai_api_key="test-key",
            include_treatment_codes=False,
            was_just_locked=True
        )

        # Should have called cache.set to store the key
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == f"lock:{note.id}"  # Cache key
        assert call_args[1]['timeout_seconds'] == 300  # 5 minutes
