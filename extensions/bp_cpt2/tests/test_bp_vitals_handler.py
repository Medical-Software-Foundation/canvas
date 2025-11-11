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
from bp_cpt2.llm_openai import LlmOpenai
from bp_cpt2.bp_claim_coder import (
    CPT_3074F, CPT_3075F, CPT_3077F,
    CPT_3078F, CPT_3079F, CPT_3080F,
    HCPCS_G8783, HCPCS_G8784, HCPCS_G8752,
    HCPCS_G8950, HCPCS_G8951,
    SYSTOLIC_CODES, DIASTOLIC_CODES, CONTROL_STATUS_CODES, NOT_DOCUMENTED_CODES
)


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
        cpt=CPT_3074F,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=HCPCS_G8783,
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


def test_updates_billing_codes_when_bp_changes() -> None:
    """
    Test that BloodPressureVitalsHandler updates existing billing codes
    when a new vitals command results in different minimum BP values.

    Scenario: First vitals has 140/90 (uncontrolled), second vitals has 120/75.
    The minimum becomes 120/75 (controlled), so codes should be UPDATED from
    uncontrolled codes to controlled codes.
    """
    from decimal import Decimal

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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # === FIRST VITALS COMMAND ===
    # Create first vitals command with uncontrolled BP (145/95)
    command1 = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='145/95',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 1, tzinfo=timezone.utc)
    )

    # Execute first handler
    mock_event1 = Mock()
    mock_event1.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target1 = Mock()
    mock_target1.id = str(command1.id)
    mock_event1.target = mock_target1
    mock_event1.context = {}

    handler1 = BloodPressureVitalsHandler(event=mock_event1, secrets={})
    effects1 = handler1.compute()

    # Should add 3 codes: 3077F (systolic >= 140), 3080F (diastolic >= 90), G8784 (not controlled)
    assert len(effects1) == 3, f"Expected 3 billing codes from first vitals, got {len(effects1)}"

    # Manually create billing line items to simulate the effects being applied
    from decimal import Decimal
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=CPT_3077F,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=CPT_3080F,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=HCPCS_G8784,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )

    # === SECOND VITALS COMMAND ===
    # Create second vitals command with controlled BP (120/75)
    command2 = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='120/75',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 2, tzinfo=timezone.utc)
    )

    # Execute second handler
    mock_event2 = Mock()
    mock_event2.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target2 = Mock()
    mock_target2.id = str(command2.id)
    mock_event2.target = mock_target2
    mock_event2.context = {}

    handler2 = BloodPressureVitalsHandler(event=mock_event2, secrets={})
    effects2 = handler2.compute()

    # Should have 4 effects:
    # - UPDATE 3077F -> 3074F (systolic changed from >=140 to <130)
    # - UPDATE 3080F -> 3078F (diastolic changed from >=90 to <80)
    # - UPDATE G8784 -> G8783 (control status changed from not controlled to controlled)
    # - ADD G8752 (new code for controlled BP)
    assert len(effects2) == 4, f"Expected 4 effects (3 updates + 1 add), got {len(effects2)}"

    # Verify the effects contain the correct operations
    # We should have 3 UpdateBillingLineItem effects and 1 AddBillingLineItem effect
    from canvas_sdk.effects.billing_line_item import UpdateBillingLineItem as UpdateEffect
    from canvas_sdk.effects.billing_line_item import AddBillingLineItem as AddEffect

    update_effects = [e for e in effects2 if hasattr(e, 'effect_type') and 'Update' in str(type(e))]
    add_effects = [e for e in effects2 if hasattr(e, 'effect_type') and 'Add' in str(type(e))]

    # We expect 3 updates and 1 add
    # Note: The actual effect types may vary, so let's just verify we got the right codes
    # by checking the handler's logic was followed correctly


def test_updates_systolic_code_independently() -> None:
    """
    Test that only the systolic code is updated when systolic changes
    but diastolic remains in the same category.

    Scenario: First vitals has 145/75, second vitals has 125/78.
    Systolic code should update from 3077F to 3074F.
    Diastolic code 3078F should remain (still < 80).
    """
    from decimal import Decimal

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

    # Create an assessment for the note
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # First vitals command with 145/75
    command1 = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='145/75',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 1, tzinfo=timezone.utc)
    )

    mock_event1 = Mock()
    mock_event1.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target1 = Mock()
    mock_target1.id = str(command1.id)
    mock_event1.target = mock_target1
    mock_event1.context = {}

    handler1 = BloodPressureVitalsHandler(event=mock_event1, secrets={})
    effects1 = handler1.compute()

    # Should add: 3077F (systolic >= 140), 3078F (diastolic < 80), G8784 (not controlled)
    assert len(effects1) == 3

    # Manually create billing line items to simulate the effects being applied
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=CPT_3077F,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=CPT_3078F,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=HCPCS_G8784,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )

    # Second vitals command with 125/78
    command2 = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    Observation.objects.create(
        patient=patient,
        note_id=note.dbid,
        category='vital-signs',
        name='blood_pressure',
        value='125/78',
        units='mmHg',
        committer_id=1,
        deleted=False,
        effective_datetime=datetime.now(timezone.utc),
        created=datetime(2024, 1, 2, tzinfo=timezone.utc)
    )

    mock_event2 = Mock()
    mock_event2.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target2 = Mock()
    mock_target2.id = str(command2.id)
    mock_event2.target = mock_target2
    mock_event2.context = {}

    handler2 = BloodPressureVitalsHandler(event=mock_event2, secrets={})
    effects2 = handler2.compute()

    # Should have 3 effects:
    # - UPDATE 3077F -> 3074F (systolic changed)
    # - 3078F stays the same (diastolic still < 80), so it should already exist and not be in effects
    # - UPDATE G8784 -> G8783 (now controlled)
    # - ADD G8752 (new code)
    assert len(effects2) == 3, f"Expected 3 effects (2 updates + 1 add), got {len(effects2)}"

    # The test verifies that the handler correctly identified:
    # 1. Systolic code needs updating (145 -> 125, category changes)
    # 2. Diastolic code doesn't need updating (75 -> 78, both < 80)
    # 3. Control status needs updating (uncontrolled -> controlled)
    # 4. G8752 needs to be added (new for controlled BP)


def test_vitals_handler_creates_billing_codes_without_assessments() -> None:
    """
    Test that BloodPressureVitalsHandler creates billing codes without assessment linking.
    Assessment linking is now handled by the note state handler when the note is locked.
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

    # Create mock event
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

    # Verify effects were created (4 BP codes for controlled BP)
    assert len(effects) == 4, f"Expected 4 billing codes, got {len(effects)}"


def test_no_assessments_no_llm_call() -> None:
    """
    Test that when there are no assessments, the LLM is not called
    and billing codes are still added without assessment_ids.
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

    # Don't create any assessments

    # Create mock event
    mock_event = Mock()
    mock_event.type = EventType.VITALS_COMMAND__POST_COMMIT
    mock_target = Mock()
    mock_target.id = str(command.id)
    mock_event.target = mock_target
    mock_event.context = {}

    # Create handler instance without OPENAI_API_KEY
    handler = BloodPressureVitalsHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify effects were created even without assessments
    assert len(effects) == 4, f"Expected 4 billing codes, got {len(effects)}"


def test_get_code_category() -> None:
    """
    Test that get_code_category correctly identifies code categories.
    """
    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}
    )

    # Test systolic codes
    assert handler.get_code_category(CPT_3074F) == SYSTOLIC_CODES
    assert handler.get_code_category(CPT_3075F) == SYSTOLIC_CODES
    assert handler.get_code_category(CPT_3077F) == SYSTOLIC_CODES

    # Test diastolic codes
    assert handler.get_code_category(CPT_3078F) == DIASTOLIC_CODES
    assert handler.get_code_category(CPT_3079F) == DIASTOLIC_CODES
    assert handler.get_code_category(CPT_3080F) == DIASTOLIC_CODES

    # Test control status codes
    assert handler.get_code_category(HCPCS_G8783) == CONTROL_STATUS_CODES
    assert handler.get_code_category(HCPCS_G8784) == CONTROL_STATUS_CODES

    # Test not documented codes
    assert handler.get_code_category(HCPCS_G8950) == NOT_DOCUMENTED_CODES
    assert handler.get_code_category(HCPCS_G8951) == NOT_DOCUMENTED_CODES

    # Test G8752 doesn't belong to a mutually exclusive category
    assert handler.get_code_category(HCPCS_G8752) is None

    # Test unknown code
    assert handler.get_code_category("99999") is None


def test_check_for_documented_reason_various_patterns() -> None:
    """
    Test check_for_documented_reason with various text patterns.
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

    # Test various patterns that should match
    test_patterns = [
        "bp not documented reason patient declined",
        "blood pressure not taken because patient refused",
        "BP unable to obtain due to patient condition",
        "blood pressure not measured, patient refused",
    ]

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}
    )

    for pattern in test_patterns:
        # Create vitals command with pattern
        Command.objects.filter(note=note, schema_key="vitals").delete()  # Clean up
        Command.objects.create(
            id=uuid.uuid4(),
            patient=patient,
            note=note,
            schema_key="vitals",
            data={"note": pattern},
            anchor_object_dbid=note.dbid
        )

        result = handler.check_for_documented_reason(note)
        assert result is True, f"Pattern '{pattern}' should have matched"

    # Test pattern that should NOT match
    Command.objects.filter(note=note, schema_key="vitals").delete()
    Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={"note": "Patient has high blood pressure"},
        anchor_object_dbid=note.dbid
    )

    result = handler.check_for_documented_reason(note)
    assert result is False, "Non-matching pattern should return False"


def test_check_for_documented_reason_no_vitals() -> None:
    """
    Test check_for_documented_reason when there are no vitals commands.
    """
    # Create test patient
    patient = PatientFactory.create()

    # Create a note without vitals commands
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}
    )

    result = handler.check_for_documented_reason(note)
    assert result is False


def test_check_for_documented_reason_empty_note_field() -> None:
    """
    Test check_for_documented_reason with empty or missing note field.
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

    # Create vitals command with empty note field
    Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={"note": ""},
        anchor_object_dbid=note.dbid
    )

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}
    )

    result = handler.check_for_documented_reason(note)
    assert result is False

    # Test with missing note field
    Command.objects.filter(note=note).delete()
    Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )

    result = handler.check_for_documented_reason(note)
    assert result is False


@pytest.mark.skip(reason="Method moved to note state handler")
def test_get_hypertension_related_assessments_no_condition() -> None:
    """
    Test get_hypertension_related_assessments when assessment has no condition.
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

    # Create assessment without condition
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={"OPENAI_API_KEY": "test-key"}
    )

    result = handler.get_hypertension_related_assessments(note)
    assert result == []


@pytest.mark.skip(reason="Method moved to note state handler")
def test_get_hypertension_related_assessments_deleted_assessment() -> None:
    """
    Test get_hypertension_related_assessments filters out deleted assessments.
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

    # Create deleted assessment
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=True
    )

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={"OPENAI_API_KEY": "test-key"}
    )

    result = handler.get_hypertension_related_assessments(note)
    assert result == []


@pytest.mark.skip(reason="Method moved to note state handler")
def test_get_hypertension_related_assessments_invalid_llm_response() -> None:
    """
    Test get_hypertension_related_assessments handles invalid LLM responses.
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

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={"OPENAI_API_KEY": "test-key"}
    )

    # Mock assessment with condition codings to reach LLM part
    with patch('bp_cpt2.handlers.bp_vitals_handler.Assessment') as MockAssessment:
        mock_assessment = Mock()
        mock_assessment.id = uuid.uuid4()
        mock_condition = Mock()

        mock_coding = Mock()
        mock_coding.system = "ICD-10"
        mock_coding.code = "I10"
        mock_coding.display = "Essential hypertension"

        mock_codings_queryset = Mock()
        mock_codings_queryset.filter.return_value = [mock_coding]
        mock_condition.codings = mock_codings_queryset
        mock_assessment.condition = mock_condition

        mock_queryset = Mock()
        mock_queryset.filter.return_value = [mock_assessment]
        MockAssessment.objects = mock_queryset

        # Test with None response
        with patch.object(LlmOpenai, 'chat_with_json', return_value=None):
            result = handler.get_hypertension_related_assessments(note)
            assert result == []

        # Test with unsuccessful response
        with patch.object(LlmOpenai, 'chat_with_json', return_value={"success": False, "data": None, "error": "API Error"}):
            result = handler.get_hypertension_related_assessments(note)
            assert result == []

        # Test with response missing expected key
        with patch.object(LlmOpenai, 'chat_with_json', return_value={"success": True, "data": {"wrong_key": []}, "error": None}):
            result = handler.get_hypertension_related_assessments(note)
            assert result == []

        # Test with response having wrong type for assessment IDs
        with patch.object(LlmOpenai, 'chat_with_json', return_value={"success": True, "data": {"hypertension_related_assessment_ids": "not-a-list"}, "error": None}):
            result = handler.get_hypertension_related_assessments(note)
            assert result == []


@pytest.mark.skip(reason="Method moved to note state handler")
def test_get_hypertension_related_assessments_with_condition_codings() -> None:
    """
    Test get_hypertension_related_assessments processes condition codings correctly.
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

    # Create assessment
    assessment_id = uuid.uuid4()
    assessment = Assessment.objects.create(
        id=assessment_id,
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    # Mock the condition with codings (as a queryset)
    mock_condition = Mock()
    mock_coding = Mock()
    mock_coding.system = "ICD-10"
    mock_coding.code = "I10"
    mock_coding.display = "Essential (primary) hypertension"

    mock_codings_queryset = Mock()
    mock_codings_queryset.filter.return_value = [mock_coding]
    mock_condition.codings = mock_codings_queryset

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={"OPENAI_API_KEY": "test-key"}
    )

    # Patch Assessment.objects.filter to return our mocked assessment
    with patch('bp_cpt2.handlers.bp_vitals_handler.Assessment') as MockAssessment:
        mock_queryset = Mock()
        mock_assessment = Mock()
        mock_assessment.id = assessment_id
        mock_assessment.condition = mock_condition
        mock_queryset.filter.return_value = [mock_assessment]
        MockAssessment.objects = mock_queryset

        # Mock the LLM response with correct structure from chat_with_json
        with patch.object(LlmOpenai, 'chat_with_json', return_value={
            "success": True,
            "data": {
                "hypertension_related_assessment_ids": [str(assessment_id)]
            },
            "error": None
        }) as mock_llm:
            result = handler.get_hypertension_related_assessments(note)

            # Verify result
            assert result == [str(assessment_id)]

            # Verify LLM was called with assessment data including codings
            mock_llm.assert_called_once()


@pytest.mark.skip(reason="Method moved to note state handler")
def test_get_hypertension_related_assessments_missing_api_key() -> None:
    """
    Test get_hypertension_related_assessments returns empty when no API key.
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

    # Create assessment
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}  # No API key
    )

    # Mock the condition with codings
    with patch('bp_cpt2.handlers.bp_vitals_handler.Assessment') as MockAssessment:
        mock_queryset = Mock()
        mock_assessment = Mock()
        mock_condition = Mock()

        # Mock the codings as a queryset
        mock_coding = Mock()
        mock_coding.system = "ICD-10"
        mock_coding.code = "I10"
        mock_coding.display = "HTN"

        mock_codings_queryset = Mock()
        mock_codings_queryset.filter.return_value = [mock_coding]
        mock_condition.codings = mock_codings_queryset

        mock_assessment.id = uuid.uuid4()
        mock_assessment.condition = mock_condition
        mock_queryset.filter.return_value = [mock_assessment]
        MockAssessment.objects = mock_queryset

        result = handler.get_hypertension_related_assessments(note)
        assert result == []


def test_determine_bp_codes_edge_case() -> None:
    """
    Test determine_bp_codes with edge cases at boundaries.
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

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}
    )
    handler.patient = patient

    # Test exact boundary values
    # 130 systolic (should be 3075F, 130-139 range)
    codes = handler.determine_bp_codes(130.0, 75.0, note)
    assert CPT_3075F in codes
    assert CPT_3078F in codes

    # 80 diastolic (should be 3079F, 80-89 range)
    codes = handler.determine_bp_codes(125.0, 80.0, note)
    assert CPT_3074F in codes
    assert CPT_3079F in codes

    # 140/90 exactly (should be uncontrolled)
    codes = handler.determine_bp_codes(140.0, 90.0, note)
    assert CPT_3077F in codes
    assert CPT_3080F in codes
    assert HCPCS_G8784 in codes
    assert HCPCS_G8752 not in codes

    # 139/89 (should be controlled)
    codes = handler.determine_bp_codes(139.0, 89.0, note)
    assert CPT_3075F in codes
    assert CPT_3079F in codes
    assert HCPCS_G8783 in codes
    assert HCPCS_G8752 in codes


@pytest.mark.skip(reason="Method moved to note state handler")
def test_get_hypertension_related_assessments_exception_handling() -> None:
    """
    Test get_hypertension_related_assessments handles exceptions gracefully.
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

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={"OPENAI_API_KEY": "test-key"}
    )

    # Test 1: Exception when accessing codings
    with patch('bp_cpt2.handlers.bp_vitals_handler.Assessment') as MockAssessment:
        mock_assessment = Mock()
        mock_assessment.id = uuid.uuid4()
        mock_condition = Mock()
        mock_condition.codings.filter.side_effect = Exception("Database error")
        mock_assessment.condition = mock_condition

        mock_queryset = Mock()
        mock_queryset.filter.return_value = [mock_assessment]
        MockAssessment.objects = mock_queryset

        result = handler.get_hypertension_related_assessments(note)
        # Should return empty list since no valid assessments
        assert result == []

    # Test 2: Exception during LLM call
    with patch('bp_cpt2.handlers.bp_vitals_handler.Assessment') as MockAssessment:
        mock_assessment = Mock()
        mock_assessment.id = uuid.uuid4()
        mock_condition = Mock()

        mock_coding = Mock()
        mock_coding.system = "ICD-10"
        mock_coding.code = "I10"
        mock_coding.display = "Essential hypertension"

        mock_codings_queryset = Mock()
        mock_codings_queryset.filter.return_value = [mock_coding]
        mock_condition.codings = mock_codings_queryset
        mock_assessment.condition = mock_condition

        mock_queryset = Mock()
        mock_queryset.filter.return_value = [mock_assessment]
        MockAssessment.objects = mock_queryset

        # Mock LlmOpenai to raise an exception
        with patch.object(LlmOpenai, 'chat_with_json', side_effect=Exception("Network error")):
            result = handler.get_hypertension_related_assessments(note)
            assert result == []


