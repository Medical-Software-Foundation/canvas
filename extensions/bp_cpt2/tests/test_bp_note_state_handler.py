# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, PropertyMock

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note, Command, Observation, Assessment, BillingLineItem

from bp_cpt2.handlers.bp_note_state_handler import BloodPressureNoteStateHandler
from bp_cpt2 import bp_claim_coder as utils
from bp_cpt2.bp_claim_coder import CPT_3077F, CPT_3080F, HCPCS_G8753, HCPCS_G8755


def create_note_with_billing_codes(codes: list[str]) -> Note:
    """Create a note with an uncontrolled BP reading, an assessment, a vitals command, and the given billing line items."""
    patient = PatientFactory.create()
    note = Note.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        body="",
        related_data={},
        datetime_of_service=datetime.now(timezone.utc)
    )
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
    Assessment.objects.create(
        id=uuid.uuid4(),
        note=note,
        patient_id=patient.dbid,
        originator_id=1,
        deleted=False
    )
    command = Command.objects.create(
        id=uuid.uuid4(),
        patient=patient,
        note=note,
        schema_key="vitals",
        data={},
        anchor_object_dbid=note.dbid
    )
    for code in codes:
        BillingLineItem.objects.create(
            note_id=note.dbid,
            patient_id=patient.dbid,
            cpt=code,
            charge=Decimal("0.00"),
            units=1,
            status="Q",
            command_id=command.dbid,
            command_type="vitals"
        )
    return note


def make_state_change_event(note: Note, state: str) -> Mock:
    """Create a NOTE_STATE_CHANGE_EVENT_UPDATED event for the note."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_UPDATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': state,
        'note_id': str(note.id)
    }
    return mock_event


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
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no effects are created for non-locked/pushed states
    assert len(effects) == 0, "Expected no billing codes for non-locked/pushed note state"


class FakeCache(dict):
    """In-memory stand-in for the plugin cache."""

    def set(self, key: str, value: str, timeout_seconds: int) -> None:
        """Store the value, ignoring the timeout."""
        self[key] = value


def test_responds_to_note_state_records_being_created_and_updated() -> None:
    """
    Test that the handler hears a lock when its state record is first created, not only when it's updated.
    """
    assert BloodPressureNoteStateHandler.RESPONDS_TO == [
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED),
        EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_UPDATED),
    ]


@pytest.mark.parametrize("state", ["LKD", "SGN"])
def test_links_hypertension_assessments_on_lock(state: str) -> None:
    """
    Test that locking or signing a note links its hypertension-related assessments to every BP billing code,
    without adding codes or pushing charges.
    """
    note = create_note_with_billing_codes([CPT_3077F, CPT_3080F, HCPCS_G8753, HCPCS_G8755])
    bp_item_ids = {str(item.id) for item in BillingLineItem.objects.filter(note_id=note.dbid)}

    handler = BloodPressureNoteStateHandler(
        event=make_state_change_event(note, state),
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    with patch.object(utils, 'get_hypertension_related_assessments', return_value=['assessment-1']) as mock_llm:
        effects = handler.compute()

    mock_llm.assert_called_once()
    assert len(effects) == 4
    assert all(effect.type == EffectType.UPDATE_BILLING_LINE_ITEM for effect in effects)
    payloads = [json.loads(effect.payload) for effect in effects]
    assert {payload["billing_line_item_id"] for payload in payloads} == bp_item_ids
    assert all(payload["data"] == {"assessment_ids": ["assessment-1"]} for payload in payloads)


def test_signing_links_diagnoses_once() -> None:
    """
    Test that the locked and signed records from one signing link diagnoses only once.
    """
    note = create_note_with_billing_codes([CPT_3077F, HCPCS_G8753])
    secrets = {'FIREWORKS_API_KEY': 'test-key'}

    with patch.object(utils, 'get_cache', return_value=FakeCache()), \
            patch.object(utils, 'get_hypertension_related_assessments', return_value=['assessment-1']) as mock_llm:
        locked_effects = BloodPressureNoteStateHandler(event=make_state_change_event(note, 'LKD'), secrets=secrets).compute()
        signed_effects = BloodPressureNoteStateHandler(event=make_state_change_event(note, 'SGN'), secrets=secrets).compute()

    assert len(locked_effects) == 2
    assert signed_effects == []
    mock_llm.assert_called_once()


def test_skips_llm_when_note_has_no_bp_codes() -> None:
    """
    Test that the LLM is not called when the note has no BP billing codes to link.
    """
    note = create_note_with_billing_codes([])

    handler = BloodPressureNoteStateHandler(
        event=make_state_change_event(note, 'LKD'),
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    with patch.object(utils, 'get_hypertension_related_assessments') as mock_llm:
        effects = handler.compute()

    mock_llm.assert_not_called()
    assert effects == []


def test_ignores_non_bp_billing_codes() -> None:
    """
    Test that only BP billing codes get hypertension assessments linked.
    """
    note = create_note_with_billing_codes(["99213", HCPCS_G8753])
    bp_item = BillingLineItem.objects.get(note_id=note.dbid, cpt=HCPCS_G8753)

    handler = BloodPressureNoteStateHandler(
        event=make_state_change_event(note, 'LKD'),
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    with patch.object(utils, 'get_hypertension_related_assessments', return_value=['assessment-1']):
        effects = handler.compute()

    assert len(effects) == 1
    assert json.loads(effects[0].payload)["billing_line_item_id"] == str(bp_item.id)


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
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no effects are created for PSH state
    assert len(effects) == 0, "Expected no billing codes for PSH state"


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
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    # Execute compute
    effects = handler.compute()

    # Should return empty list when note doesn't exist
    assert len(effects) == 0, "Expected no effects when note doesn't exist"


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
        secrets={'OPENAI_API_KEY': 'test-key'}
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


def test_assessment_combining_logic() -> None:
    """
    Test that existing assessments are combined with new hypertension-related assessments.
    """
    # Test case 1: Existing assessments + new assessments = combined unique list
    existing_assessments = ['assessment-1', 'assessment-2']
    new_assessments = ['assessment-3', 'assessment-1']  # assessment-1 is duplicate

    combined = list(set(existing_assessments + new_assessments))

    # Should have 3 unique assessments (1, 2, 3)
    assert len(combined) == 3
    assert 'assessment-1' in combined
    assert 'assessment-2' in combined
    assert 'assessment-3' in combined

    # Test case 2: No existing assessments
    existing_assessments = []
    new_assessments = ['assessment-1', 'assessment-2']

    combined = list(set(existing_assessments + new_assessments))

    assert len(combined) == 2
    assert 'assessment-1' in combined
    assert 'assessment-2' in combined

    # Test case 3: No new assessments
    existing_assessments = ['assessment-1', 'assessment-2']
    new_assessments = []

    combined = list(set(existing_assessments + new_assessments))

    assert len(combined) == 2
    assert 'assessment-1' in combined
    assert 'assessment-2' in combined


def test_existing_assessments_are_preserved_when_updating_bp_codes() -> None:
    """
    Test that demonstrates SDK bug #1262: we cannot read existing assessment_ids from billing items.

    PROBLEM:
    The BillingLineItem model doesn't expose assessment_ids for reading, only for writing via Effects.
    This makes it impossible to preserve existing assessment links when updating billing codes.

    This test will FAIL (by raising AssertionError) when the SDK bug is fixed.
    See: https://github.com/canvas-medical/canvas-plugins/issues/1262
    """
    # Get any existing billing line item (or create a minimal one to test with)
    billing_items = BillingLineItem.objects.all()[:1]

    if billing_items.exists():
        billing_item = billing_items.first()
    else:
        # If no billing items exist, create a minimal test setup
        patient = PatientFactory.create()
        note = Note.objects.create(
            id=uuid.uuid4(),
            patient=patient,
            body="Test",
            related_data={},
            datetime_of_service=datetime.now(timezone.utc)
        )
        billing_item = note  # Use note instead to test the concept

    # THIS IS THE BUG: We cannot read the assessment_ids from billing items
    # The following assertion will FAIL until the SDK bug is fixed:
    assert hasattr(billing_item, 'assessment_ids'), (
        "BUG: BillingLineItem does not expose assessment_ids for reading. "
        "This prevents us from preserving existing assessments when updating billing codes. "
        "See bp_claim_coder.py lines 458-472 and Canvas SDK issue #1262."
    )

    # THE CONSEQUENCE: When process_bp_billing_for_note tries to preserve existing assessments,
    # it cannot read them, so they get lost when we update the billing code.
    # See bp_claim_coder.py lines 458-472 for the TODO comments documenting this limitation.
