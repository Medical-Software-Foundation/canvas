# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch, PropertyMock

from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Command, Observation, Assessment

from bp_cpt2.handlers.bp_note_state_handler import BloodPressureNoteStateHandler


def test_skips_non_locked_non_pushed_states() -> None:
    """
    Test that handler skips processing for note states other than LKD or PSH.
    """
    # Create mock event for note state change to NEW (not locked or pushed)
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'NEW',
        'note_id': str(uuid.uuid4())
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no effects are created for non-locked/pushed states
    assert len(effects) == 0, "Expected no billing codes for non-locked/pushed note state"


def test_processes_locked_state() -> None:
    """
    Test that handler processes notes in LKD state.
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

    # Create BP observation - uncontrolled BP (145/95)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='145/95',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event for note state change to LKD
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LLM call to return that treatment plan is documented
    with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_llm:
        mock_llm.return_value = {
            "has_treatment_plan": True,
            "has_documented_reason": False,
            "explanation": "Patient prescribed lisinopril 10mg daily"
        }

        # Execute compute
        effects = handler.compute()

        # Verify LLM was called
        mock_llm.assert_called_once()

        # Verify that G8753 code is added (treatment plan documented)
        assert len(effects) == 1, "Expected 1 billing code for treatment plan documented"


def test_skips_pushed_state() -> None:
    """
    Test that handler does NOT process notes in PSH (pushed) state.
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

    # Create BP observation - uncontrolled BP (145/95)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='145/95',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event for note state change to PSH
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'PSH',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no effects are created for PSH state
    assert len(effects) == 0, "Expected no billing codes for PSH state"


def test_skips_controlled_blood_pressure() -> None:
    """
    Test that handler skips treatment codes for controlled BP (< 140/90).
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

    # Create BP observation - controlled BP (120/75)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='120/75',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc)
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no treatment codes are added for controlled BP
    assert len(effects) == 0, "Expected no treatment codes for controlled BP"


def test_skips_when_no_bp_readings() -> None:
    """
    Test that handler skips when no BP readings are found.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note WITHOUT BP observations
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no treatment codes are added when no BP readings
    assert len(effects) == 0, "Expected no treatment codes when no BP readings"


def test_adds_g8753_when_treatment_plan_documented() -> None:
    """
    Test that handler adds G8753 when treatment plan is documented.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LLM call to return that treatment plan is documented
    with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_llm:
        mock_llm.return_value = {
            "has_treatment_plan": True,
            "has_documented_reason": False,
            "explanation": "Started amlodipine 5mg daily for hypertension"
        }

        # Execute compute
        effects = handler.compute()

        # Verify that G8753 is added
        assert len(effects) == 1, "Expected 1 billing code (G8753)"


def test_adds_g8754_when_no_treatment_plan_no_reason() -> None:
    """
    Test that handler adds G8754 when no treatment plan and no documented reason.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LLM call to return no treatment plan and no reason
    with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_llm:
        mock_llm.return_value = {
            "has_treatment_plan": False,
            "has_documented_reason": False,
            "explanation": "No treatment plan found in documentation"
        }

        # Execute compute
        effects = handler.compute()

        # Verify that G8754 is added
        assert len(effects) == 1, "Expected 1 billing code (G8754)"


def test_adds_g8755_when_no_treatment_plan_with_reason() -> None:
    """
    Test that handler adds G8755 when no treatment plan but has documented reason.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LLM call to return no treatment plan but with documented reason
    with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_llm:
        mock_llm.return_value = {
            "has_treatment_plan": False,
            "has_documented_reason": True,
            "explanation": "Patient declined medication changes, awaiting cardiology consult"
        }

        # Execute compute
        effects = handler.compute()

        # Verify that G8755 is added
        assert len(effects) == 1, "Expected 1 billing code (G8755)"


def test_handles_missing_openai_api_key() -> None:
    """
    Test that handler handles missing OpenAI API key gracefully.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance WITHOUT API key
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that G8754 is added as default when API key is missing
    assert len(effects) == 1, "Expected 1 billing code (G8754 as default)"


def test_prepare_note_commands_data() -> None:
    """
    Test that note commands are properly formatted for LLM analysis.
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

    # Create some commands
    Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="prescribe",
        data={"medication": "lisinopril 10mg", "instructions": "take daily"},
        anchor_object_dbid=note.dbid
    )

    Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="plan",
        data={"plan": "recheck BP in 2 weeks"},
        anchor_object_dbid=note.dbid
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_event.target = Mock()
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Test prepare_note_commands_data
    commands_data = handler.prepare_note_commands_data(note)

    # Verify commands are in the output
    assert "prescribe" in commands_data
    assert "lisinopril" in commands_data
    assert "plan" in commands_data


def test_prepare_medications_data_no_medications() -> None:
    """
    Test that medication data preparation handles no medications gracefully.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_event.target = Mock()
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Test prepare_medications_data with no medications
    medications_data = handler.prepare_medications_data(str(patient.id))

    # Verify appropriate message
    assert "No active medications" in medications_data


def test_no_duplicate_treatment_codes() -> None:
    """
    Test that handler does not add duplicate treatment codes.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create a command for the billing line item
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="assess",
        data={},
        anchor_object_dbid=note.dbid
    )

    # Pre-create the G8753 billing line item
    from decimal import Decimal
    from canvas_sdk.v1.data import BillingLineItem
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt="G8753",
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command.dbid,
        command_type="assess"
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LLM call
    with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_llm:
        mock_llm.return_value = {
            "has_treatment_plan": True,
            "has_documented_reason": False,
            "explanation": "Treatment documented"
        }

        # Execute compute
        effects = handler.compute()

        # Should not add duplicate - expect 0 effects
        assert len(effects) == 0, "Expected no effects (code already exists)"


def test_prepare_medications_data_with_medications() -> None:
    """
    Test that medication data preparation formats medications correctly.
    """
    from canvas_sdk.v1.data import Medication

    # Create test patient
    patient = PatientFactory.create()

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_event.target = Mock()
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock Medication.objects.for_patient to return mock medications
    mock_med1 = Mock()
    mock_med1.fhir_medication_display = "Lisinopril 10mg"
    mock_med1.status = "active"

    mock_med2 = Mock()
    mock_med2.fhir_medication_display = "Amlodipine 5mg"
    mock_med2.status = "active"

    with patch.object(Medication.objects, 'for_patient') as mock_for_patient:
        mock_queryset = Mock()
        mock_queryset.filter.return_value = [mock_med1, mock_med2]
        mock_for_patient.return_value = mock_queryset

        # Test prepare_medications_data with medications
        medications_data = handler.prepare_medications_data(str(patient.id))

        # Verify medications are in the output
        assert "Lisinopril" in medications_data
        assert "Amlodipine" in medications_data
        assert "active" in medications_data


def test_note_not_found() -> None:
    """
    Test that handler handles Note.DoesNotExist gracefully.
    """
    # Create a fake note ID that doesn't exist
    fake_note_id = str(uuid.uuid4())

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': fake_note_id
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Execute compute
    effects = handler.compute()

    # Should return empty list when note doesn't exist
    assert len(effects) == 0, "Expected no effects when note doesn't exist"


def test_full_llm_analysis_success() -> None:
    """
    Test the full LLM analysis path when API key is provided and call succeeds.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance WITH API key
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key-12345', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LlmOpenai class to return a successful response
    with patch('bp_cpt2.handlers.bp_note_state_handler.LlmOpenai') as mock_llm_class:
        mock_llm_instance = Mock()
        mock_llm_class.return_value = mock_llm_instance

        # Mock successful JSON response
        mock_llm_instance.chat_with_json.return_value = {
            "success": True,
            "data": {
                "has_treatment_plan": True,
                "has_documented_reason": False,
                "explanation": "Patient started on lisinopril 10mg"
            },
            "error": None
        }

        # Execute compute
        effects = handler.compute()

        # Verify LLM was instantiated with correct parameters
        mock_llm_class.assert_called_once_with(api_key='test-key-12345', model='gpt-4')

        # Verify chat_with_json was called
        mock_llm_instance.chat_with_json.assert_called_once()

        # Verify that G8753 code is added
        assert len(effects) == 1, "Expected 1 billing code (G8753)"


def test_full_llm_analysis_failure() -> None:
    """
    Test the full LLM analysis path when LLM call fails.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance WITH API key
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key-12345', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the LlmOpenai class to return a failed response
    with patch('bp_cpt2.handlers.bp_note_state_handler.LlmOpenai') as mock_llm_class:
        mock_llm_instance = Mock()
        mock_llm_class.return_value = mock_llm_instance

        # Mock failed JSON response (API error)
        mock_llm_instance.chat_with_json.return_value = {
            "success": False,
            "data": None,
            "error": "API rate limit exceeded"
        }

        # Execute compute
        effects = handler.compute()

        # Should still add a code (G8754 as default)
        assert len(effects) == 1, "Expected 1 billing code (G8754 as fallback)"


def test_determine_treatment_code_none_edge_case() -> None:
    """
    Test edge case where determine_treatment_code might return None.
    This shouldn't happen in practice but tests defensive code.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock analyze_treatment_plan_with_llm to return result
    # and determine_treatment_code to return None
    with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_analyze:
        mock_analyze.return_value = {
            "has_treatment_plan": False,
            "has_documented_reason": False,
            "explanation": "Test"
        }

        with patch.object(handler, 'determine_treatment_code', return_value=None):
            # Execute compute
            effects = handler.compute()

            # Should return empty list when treatment_code is None
            assert len(effects) == 0, "Expected no effects when treatment_code is None"


def test_treatment_plan_codes_disabled() -> None:
    """
    Test that handler returns empty list when INCLUDE_TREATMENT_PLAN_CODES is disabled.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance WITH INCLUDE_TREATMENT_PLAN_CODES set to false
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'false'}
    )

    # Execute compute
    effects = handler.compute()

    # Should return empty list immediately
    assert len(effects) == 0, "Expected no effects when treatment codes are disabled"


def test_skips_non_billable_note() -> None:
    """
    Test that handler skips processing when note type is not billable.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the note_type_version to have is_billable = False
    mock_note_type = Mock()
    mock_note_type.is_billable = False

    with patch.object(Note.objects, 'get', return_value=note):
        with patch.object(type(note), 'note_type_version', new_callable=PropertyMock, return_value=mock_note_type):
            # Execute compute
            effects = handler.compute()

            # Should return empty list when note is not billable
            assert len(effects) == 0, "Expected no effects when note type is not billable"


def test_pushes_charges_for_billable_note() -> None:
    """
    Test that handler pushes charges when note type is billable.
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

    # Create BP observation - uncontrolled BP (150/100)
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',
        'note_id': str(note.id)
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key', 'INCLUDE_TREATMENT_PLAN_CODES': 'true'}
    )

    # Mock the note_type_version to have is_billable = True
    mock_note_type = Mock()
    mock_note_type.is_billable = True

    with patch.object(Note.objects, 'get', return_value=note):
        with patch.object(type(note), 'note_type_version', new_callable=PropertyMock, return_value=mock_note_type):
            # Mock the LLM call
            with patch.object(handler, 'analyze_treatment_plan_with_llm') as mock_llm:
                mock_llm.return_value = {
                    "has_treatment_plan": True,
                    "has_documented_reason": False,
                    "explanation": "Treatment documented"
                }

                # Execute compute
                effects = handler.compute()

                # Should return 2 effects: billing item + push charges
                assert len(effects) == 2, "Expected 2 effects (billing item + push charges) for billable note"
