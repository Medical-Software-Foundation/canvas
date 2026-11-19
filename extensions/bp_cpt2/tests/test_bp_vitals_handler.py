# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Command, Observation, Assessment, BillingLineItem

from bp_cpt2.handlers.bp_vitals_handler import BloodPressureVitalsHandler
from bp_cpt2.llm_openai import LlmOpenai
from bp_cpt2.bp_claim_coder import (
    CPT_3074F, CPT_3075F, CPT_3077F,
    CPT_3078F, CPT_3079F, CPT_3080F,
    HCPCS_G8752, HCPCS_G8753, HCPCS_G8754, HCPCS_G8755,
    SYSTOLIC_CODES, DIASTOLIC_CODES, MIPS_236_SYSTOLIC_CODES, MIPS_236_DIASTOLIC_CODES
)


def effect_codes(effects: list) -> list[str]:
    """Return the code each billing line item effect adds or switches to."""
    return [json.loads(effect.payload)["data"]["cpt"] for effect in effects]


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

    # For BP 120/75, we expect:
    # - 3074F (systolic < 130)
    # - 3078F (diastolic < 80)
    # - G8752 (systolic < 140)
    # - G8754 (diastolic < 90)
    assert effect_codes(effects) == [CPT_3074F, CPT_3078F, HCPCS_G8752, HCPCS_G8754]


def test_no_bp_readings() -> None:
    """
    Test that BloodPressureVitalsHandler adds no codes
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

    # No measure 236 "not documented" code: an earlier visit may already have a BP
    assert effects == []


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
        cpt=HCPCS_G8752,
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

    # Should only add the 2 codes that don't already exist (3078F and G8754)
    # Not the 2 that already exist (3074F and G8752)
    assert effect_codes(effects) == [CPT_3078F, HCPCS_G8754]


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
    # - G8753 (systolic >= 140)
    # - G8755 (diastolic >= 90)
    assert effect_codes(effects) == [CPT_3077F, CPT_3080F, HCPCS_G8753, HCPCS_G8755]


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
    # - G8752 (systolic < 140)
    # - G8754 (diastolic < 90)
    assert effect_codes(effects) == [CPT_3075F, CPT_3079F, HCPCS_G8752, HCPCS_G8754]


def test_invalid_bp_format() -> None:
    """
    Test that BloodPressureVitalsHandler handles invalid BP format gracefully
    and adds no codes.
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

    # Parsing failed, so there is no BP to code
    assert effects == []


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

    # Should add 4 codes: 3077F (systolic >= 140), 3080F (diastolic >= 90), G8753 (systolic >= 140), G8755 (diastolic >= 90)
    assert effect_codes(effects1) == [CPT_3077F, CPT_3080F, HCPCS_G8753, HCPCS_G8755]

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
        cpt=HCPCS_G8753,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=HCPCS_G8755,
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

    # Should have 4 updates:
    # - UPDATE 3077F -> 3074F (systolic changed from >=140 to <130)
    # - UPDATE 3080F -> 3078F (diastolic changed from >=90 to <80)
    # - UPDATE G8753 -> G8752 (systolic changed from >=140 to <140)
    # - UPDATE G8755 -> G8754 (diastolic changed from >=90 to <90)
    assert effect_codes(effects2) == [CPT_3074F, CPT_3078F, HCPCS_G8752, HCPCS_G8754]
    assert all(effect.type == EffectType.UPDATE_BILLING_LINE_ITEM for effect in effects2)


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

    # Should add: 3077F (systolic >= 140), 3078F (diastolic < 80), G8753 (systolic >= 140), G8754 (diastolic < 90)
    assert effect_codes(effects1) == [CPT_3077F, CPT_3078F, HCPCS_G8753, HCPCS_G8754]

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
        cpt=HCPCS_G8753,
        charge=Decimal("0.00"),
        units=1,
        status="Q",
        command_id=command1.dbid,
        command_type="assess"
    )
    BillingLineItem.objects.create(
        note_id=note.dbid,
        patient_id=patient.dbid,
        cpt=HCPCS_G8754,
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

    # Should have 2 updates:
    # - UPDATE 3077F -> 3074F (systolic changed)
    # - UPDATE G8753 -> G8752 (systolic now < 140)
    # 3078F and G8754 stay the same (diastolic still < 80), so they are not in effects
    assert effect_codes(effects2) == [CPT_3074F, HCPCS_G8752]
    assert all(effect.type == EffectType.UPDATE_BILLING_LINE_ITEM for effect in effects2)


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

    # Verify effects were created (4 BP codes for controlled BP) with no linked assessments
    assert len(effects) == 4, f"Expected 4 billing codes, got {len(effects)}"
    assert all(json.loads(effect.payload)["data"]["assessment_ids"] == [] for effect in effects)


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

    # Test MIPS measure 236 codes
    assert handler.get_code_category(HCPCS_G8752) == MIPS_236_SYSTOLIC_CODES
    assert handler.get_code_category(HCPCS_G8753) == MIPS_236_SYSTOLIC_CODES
    assert handler.get_code_category(HCPCS_G8754) == MIPS_236_DIASTOLIC_CODES
    assert handler.get_code_category(HCPCS_G8755) == MIPS_236_DIASTOLIC_CODES

    # Test unknown code
    assert handler.get_code_category("99999") is None


def test_determine_bp_codes_edge_case() -> None:
    """
    Test determine_bp_codes with edge cases at boundaries.
    """
    # Create test patient
    patient = PatientFactory.create()

    handler = BloodPressureVitalsHandler(
        event=Mock(),
        secrets={}
    )
    handler.patient = patient

    # Test exact boundary values
    # 130 systolic (should be 3075F, 130-139 range)
    codes = handler.determine_bp_codes(130.0, 75.0)
    assert codes == [CPT_3075F, CPT_3078F, HCPCS_G8752, HCPCS_G8754]

    # 80 diastolic (should be 3079F, 80-89 range)
    codes = handler.determine_bp_codes(125.0, 80.0)
    assert codes == [CPT_3074F, CPT_3079F, HCPCS_G8752, HCPCS_G8754]

    # 140/90 exactly (both at the measure 236 threshold)
    codes = handler.determine_bp_codes(140.0, 90.0)
    assert codes == [CPT_3077F, CPT_3080F, HCPCS_G8753, HCPCS_G8755]

    # 139/89 (both just under the measure 236 threshold)
    codes = handler.determine_bp_codes(139.0, 89.0)
    assert codes == [CPT_3075F, CPT_3079F, HCPCS_G8752, HCPCS_G8754]

    # Only systolic uncontrolled - each value gets its own code
    codes = handler.determine_bp_codes(150.0, 85.0)
    assert codes == [CPT_3077F, CPT_3079F, HCPCS_G8753, HCPCS_G8754]

    # Only diastolic uncontrolled
    codes = handler.determine_bp_codes(130.0, 92.0)
    assert codes == [CPT_3075F, CPT_3080F, HCPCS_G8752, HCPCS_G8755]

    # Missing either value adds nothing
    assert handler.determine_bp_codes(None, 80.0) == []
    assert handler.determine_bp_codes(120.0, None) == []
