# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import pytest

from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Command, Observation, Assessment, BillingLineItem

from bp_cpt2.handlers.bp_vitals_handler import BloodPressureVitalsHandler


def test_controlled_blood_pressure() -> None:
    """
    Test that BloodPressureVitalsHandler correctly adds billing codes
    for controlled blood pressure (BP < 140/90).
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

    # Create a vitals command
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify effects were created
    assert len(effects) > 0, "Expected billing line item effects to be created"

    # Verify that controlled BP codes are present
    # For BP 120/75, we expect:
    # - 3074F (systolic < 130)
    # - 3078F (diastolic < 80)
    # - G8783 (BP controlled)
    # - G8752 (BP < 140/90)
    assert len(effects) == 4, f"Expected 4 billing codes for controlled BP, got {len(effects)}"


def test_no_bp_readings() -> None:
    """
    Test that BloodPressureVitalsHandler correctly adds G8950 code
    when no BP readings are documented.
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

    # Create a vitals command WITHOUT BP observations
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        data={},
        anchor_object_dbid=note.dbid
    )

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that G8950 code is added (BP not documented)
    assert len(effects) == 1, f"Expected 1 billing code (G8950) for undocumented BP, got {len(effects)}"


def test_no_bp_readings_with_documented_reason() -> None:
    """
    Test that BloodPressureVitalsHandler correctly adds G8951 code
    when no BP readings are documented but a reason is provided.
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

    # Create a vitals command WITHOUT BP observations but with a note explaining why
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={"note": "BP not documented because patient refused"},
        anchor_object_dbid=note.dbid
    )

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that G8951 code is added (BP not documented with reason)
    assert len(effects) == 1, f"Expected 1 billing code (G8951) for undocumented BP with reason, got {len(effects)}"


def test_no_duplicates_added() -> None:
    """
    Test that BloodPressureVitalsHandler does not add duplicate billing codes
    if they already exist on the note.
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

    # Create a vitals command
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Pre-create billing line items that the handler would normally add
    from decimal import Decimal
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt="3074F",
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt="G8783",
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command.dbid,
        command_type="assess"
    )

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Should only add the 2 codes that don't already exist (3078F and G8752)
    # Not the 2 that already exist (3074F and G8783)
    assert len(effects) == 2, f"Expected 2 new billing codes (skipping 2 duplicates), got {len(effects)}"


def test_uncontrolled_blood_pressure() -> None:
    """
    Test that BloodPressureVitalsHandler correctly adds billing codes
    for uncontrolled blood pressure (BP >= 140/90).
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

    # Create a vitals command
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
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

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify effects were created
    assert len(effects) > 0, "Expected billing line item effects to be created"

    # For BP 145/95, we expect:
    # - 3077F (systolic >= 140)
    # - 3080F (diastolic >= 90)
    # - G8784 (BP not controlled)
    assert len(effects) == 3, f"Expected 3 billing codes for uncontrolled BP, got {len(effects)}"


def test_borderline_high_blood_pressure() -> None:
    """
    Test that BloodPressureVitalsHandler correctly adds billing codes
    for borderline high blood pressure (130-139 / 80-89).
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

    # Create a vitals command
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    # Create BP observation - borderline BP (135/85)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='135/85',
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

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify effects were created
    assert len(effects) > 0, "Expected billing line item effects to be created"

    # For BP 135/85, we expect:
    # - 3075F (systolic 130-139)
    # - 3079F (diastolic 80-89)
    # - G8783 (BP controlled < 140/90)
    # - G8752 (Most recent BP < 140/90)
    assert len(effects) == 4, f"Expected 4 billing codes for borderline BP, got {len(effects)}"


def test_invalid_bp_format() -> None:
    """
    Test that BloodPressureVitalsHandler handles invalid BP format gracefully
    and adds G8950 code (BP not documented).
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

    # Create a vitals command
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    # Create BP observation with invalid format (has slash but non-numeric values)
    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='abc/xyz',
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

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Should add G8950 code (BP not documented) since parsing failed
    assert len(effects) == 1, f"Expected 1 billing code (G8950) for invalid BP format, got {len(effects)}"


def test_no_bp_codes_raises_exception() -> None:
    """
    Test that BloodPressureVitalsHandler raises ValueError when
    determine_bp_codes returns an empty list (defensive check).
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

    # Create a vitals command
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    # Create BP observation
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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Create mock event with proper structure
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Mock determine_bp_codes to return empty list
    with patch.object(handler, 'determine_bp_codes', return_value=[]):
        # Verify that ValueError is raised
        with pytest.raises(ValueError, match=f"No BP codes determined for patient {patient.id}"):
            handler.compute()
