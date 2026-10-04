# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Observation, Assessment, Condition, ConditionCoding

from bp_cpt2.bp_claim_coder import get_blood_pressure_readings, get_hypertension_related_assessments, get_llm_client, process_bp_billing_for_note
from bp_cpt2.llm_anthropic import ANTHROPIC_API_BASE, LlmAnthropic
from bp_cpt2.llm_openai import FIREWORKS_API_BASE, FIREWORKS_DEFAULT_MODEL, OPENAI_API_BASE, LlmOpenai


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
    llm = Mock()
    result = get_hypertension_related_assessments(note, llm)
    assert result == []
    llm.chat_with_json.assert_not_called()


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
    llm = Mock()
    result = get_hypertension_related_assessments(note, llm)
    assert result == []
    llm.chat_with_json.assert_not_called()


def test_get_hypertension_related_assessments_no_api_key() -> None:
    """
    Test get_hypertension_related_assessments without an LLM client (no AI provider key configured).
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

    # Call function without an LLM client
    result = get_hypertension_related_assessments(note, None)

    # Should return empty list
    assert result == []


def create_hypertension_assessment() -> tuple[Note, Assessment]:
    """Create a note with one assessment whose condition has an ICD-10 and a SNOMED coding."""
    patient = PatientFactory.create()
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )
    condition = Condition.objects.create(
        patient=patient,
        deleted=False,
        clinical_status="active",
        surgical=False,
        onset_date=datetime.now(timezone.utc).date(),
        resolution_date=datetime.now(timezone.utc).date()
    )
    ConditionCoding.objects.create(condition=condition, system="ICD-10", code="I10", display="Essential hypertension")
    ConditionCoding.objects.create(condition=condition, system="SNOMED", code="59621000", display="Essential hypertension")
    assessment = Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        condition=condition,
        originator_id=1,
        deleted=False
    )
    return note, assessment


def test_get_hypertension_related_assessments_returns_llm_ids() -> None:
    """
    Test that the assessment IDs the LLM marks as hypertension-related are returned,
    and that only ICD-10 codings are sent to the LLM.
    """
    note, assessment = create_hypertension_assessment()

    llm = Mock()
    llm.chat_with_json.return_value = {
        "success": True,
        "data": {"hypertension_related_assessment_ids": [str(assessment.id)]}
    }
    result = get_hypertension_related_assessments(note, llm)

    assert result == [str(assessment.id)]
    user_prompt = llm.chat_with_json.call_args.kwargs["user_prompt"]
    assert "I10" in user_prompt
    assert "59621000" not in user_prompt


def test_get_hypertension_related_assessments_without_api_key_skips_llm() -> None:
    """
    Test that assessments with codings link nothing when no AI provider key is configured.
    """
    note, _ = create_hypertension_assessment()

    assert get_hypertension_related_assessments(note, None) == []


def test_get_hypertension_related_assessments_llm_failures_return_empty() -> None:
    """
    Test that failed, malformed, or raising LLM calls link no assessments.
    """
    note, _ = create_hypertension_assessment()

    responses = [
        {"success": False, "error": "API error"},
        {"success": True, "data": {"hypertension_related_assessment_ids": "not-a-list"}},
    ]
    for response in responses:
        llm = Mock()
        llm.chat_with_json.return_value = response
        assert get_hypertension_related_assessments(note, llm) == []
        llm.chat_with_json.assert_called_once()

    llm = Mock()
    llm.chat_with_json.side_effect = RuntimeError("timeout")
    assert get_hypertension_related_assessments(note, llm) == []


def test_get_llm_client_returns_none_without_a_provider_key() -> None:
    """
    Test that no client is built when no AI provider key is set or the keys are empty.
    """
    assert get_llm_client({}) is None
    assert get_llm_client({"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "FIREWORKS_API_KEY": "", "LLM_MODEL": "gpt-4o"}) is None


def test_get_llm_client_builds_each_provider_with_its_defaults() -> None:
    """
    Test that each provider key builds a client for that provider's API and default model.
    """
    openai = get_llm_client({"OPENAI_API_KEY": "openai-key"})
    assert type(openai) is LlmOpenai
    assert (openai.api_key, openai.model, openai.base_url) == ("openai-key", "gpt-4", OPENAI_API_BASE)

    anthropic = get_llm_client({"ANTHROPIC_API_KEY": "anthropic-key"})
    assert type(anthropic) is LlmAnthropic
    assert (anthropic.api_key, anthropic.model, anthropic.base_url) == ("anthropic-key", "claude-opus-5", ANTHROPIC_API_BASE)

    fireworks = get_llm_client({"FIREWORKS_API_KEY": "fireworks-key"})
    assert type(fireworks) is LlmOpenai
    assert (fireworks.api_key, fireworks.model, fireworks.base_url) == ("fireworks-key", FIREWORKS_DEFAULT_MODEL, FIREWORKS_API_BASE)


def test_get_llm_client_prefers_openai_then_anthropic_then_fireworks() -> None:
    """
    Test which provider is used when more than one key is set.
    """
    all_keys = {"OPENAI_API_KEY": "openai-key", "ANTHROPIC_API_KEY": "anthropic-key", "FIREWORKS_API_KEY": "fireworks-key"}
    assert get_llm_client(all_keys).api_key == "openai-key"

    del all_keys["OPENAI_API_KEY"]
    assert get_llm_client(all_keys).api_key == "anthropic-key"


def test_get_llm_client_uses_llm_model_override() -> None:
    """
    Test that LLM_MODEL replaces the provider's default model.
    """
    assert get_llm_client({"ANTHROPIC_API_KEY": "anthropic-key", "LLM_MODEL": "claude-sonnet-5"}).model == "claude-sonnet-5"
    assert get_llm_client({"FIREWORKS_API_KEY": "fireworks-key", "LLM_MODEL": "accounts/fireworks/routers/glm-5p3-us"}).model == "accounts/fireworks/routers/glm-5p3-us"


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
            llm=Mock(),
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
            llm=Mock(),
            was_just_locked=True
        )

        # Should have called cache.set to store the key
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == f"lock:{note.id}"  # Cache key
        assert call_args[1]['timeout_seconds'] == 300  # 5 minutes
