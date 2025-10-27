"""
Unit tests for the database module (database.py).

Tests all database functions using an in-memory SQLite database.
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# Add intake_agent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'intake_agent'))

import database


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_intake.db"
    schema_path = Path(__file__).parent.parent.parent / 'intake_agent' / 'schema.sql'

    # Read and execute schema
    with open(schema_path, 'r') as f:
        schema = f.read()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    conn.commit()
    conn.close()

    # Patch DATABASE_PATH to use temp database
    original_path = database.DATABASE_PATH
    database.DATABASE_PATH = db_path

    yield db_path

    # Restore original path
    database.DATABASE_PATH = original_path


class TestDatabaseConnection:
    """Tests for database connection management."""

    def test_get_db_connection(self, temp_db):
        """Test that get_db_connection returns a valid connection."""
        conn = database.get_db_connection()
        assert conn is not None
        assert isinstance(conn, sqlite3.Connection)

        # Test row factory is set
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test_col")
        row = cursor.fetchone()
        assert row['test_col'] == 1

        conn.close()

    def test_foreign_keys_enabled(self, temp_db):
        """Test that foreign key constraints are enabled."""
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()
        assert result[0] == 1
        conn.close()


class TestPatientCRUD:
    """Tests for patient CRUD operations."""

    def test_create_patient_minimal(self, temp_db):
        """Test creating a patient with no data."""
        patient_id = database.create_patient()
        assert patient_id > 0

    def test_create_patient_full(self, temp_db):
        """Test creating a patient with full data."""
        patient_id = database.create_patient(
            first_name="John",
            last_name="Doe",
            date_of_birth="1990-01-15",
            sex="male",
            gender="male",
            current_health_concerns="High blood pressure"
        )
        assert patient_id > 0

        # Verify data was saved
        patient = database.get_patient(patient_id)
        assert patient['first_name'] == "John"
        assert patient['last_name'] == "Doe"
        assert patient['date_of_birth'] == "1990-01-15"
        assert patient['sex'] == "male"
        assert patient['gender'] == "male"
        assert patient['current_health_concerns'] == "High blood pressure"

    def test_get_patient_exists(self, temp_db):
        """Test retrieving an existing patient."""
        patient_id = database.create_patient(first_name="Jane", last_name="Smith")
        patient = database.get_patient(patient_id)

        assert patient is not None
        assert patient['id'] == patient_id
        assert patient['first_name'] == "Jane"
        assert patient['last_name'] == "Smith"

    def test_get_patient_not_found(self, temp_db):
        """Test retrieving a non-existent patient returns None."""
        patient = database.get_patient(9999)
        assert patient is None

    def test_get_all_patients_empty(self, temp_db):
        """Test getting all patients when database is empty."""
        patients = database.get_all_patients()
        assert patients == []

    def test_get_all_patients_multiple(self, temp_db):
        """Test getting all patients with multiple records."""
        id1 = database.create_patient(first_name="Alice")
        id2 = database.create_patient(first_name="Bob")
        id3 = database.create_patient(first_name="Charlie")

        patients = database.get_all_patients()
        assert len(patients) == 3

        # Verify all patients are returned (order may vary)
        patient_ids = {p['id'] for p in patients}
        assert patient_ids == {id1, id2, id3}

    def test_update_patient_single_field(self, temp_db):
        """Test updating a single patient field."""
        patient_id = database.create_patient(first_name="John")

        database.update_patient(patient_id, last_name="Doe")

        patient = database.get_patient(patient_id)
        assert patient['first_name'] == "John"
        assert patient['last_name'] == "Doe"

    def test_update_patient_multiple_fields(self, temp_db):
        """Test updating multiple patient fields."""
        patient_id = database.create_patient()

        database.update_patient(
            patient_id,
            first_name="Jane",
            last_name="Smith",
            date_of_birth="1995-06-20",
            sex="female"
        )

        patient = database.get_patient(patient_id)
        assert patient['first_name'] == "Jane"
        assert patient['last_name'] == "Smith"
        assert patient['date_of_birth'] == "1995-06-20"
        assert patient['sex'] == "female"

    def test_update_patient_sex_defaults_gender(self, temp_db):
        """Test that updating sex defaults gender to sex if gender is null."""
        patient_id = database.create_patient()

        database.update_patient(patient_id, sex="male")

        patient = database.get_patient(patient_id)
        assert patient['sex'] == "male"
        assert patient['gender'] == "male"

    def test_update_patient_sex_preserves_existing_gender(self, temp_db):
        """Test that updating sex doesn't override existing gender."""
        patient_id = database.create_patient(sex="male", gender="non-binary")

        database.update_patient(patient_id, first_name="Alex")

        patient = database.get_patient(patient_id)
        assert patient['gender'] == "non-binary"

    def test_update_patient_invalid_fields_ignored(self, temp_db):
        """Test that invalid update fields are ignored."""
        patient_id = database.create_patient(first_name="John")

        database.update_patient(patient_id, invalid_field="value", first_name="Jane")

        patient = database.get_patient(patient_id)
        assert patient['first_name'] == "Jane"
        assert 'invalid_field' not in patient

    def test_update_patient_no_fields(self, temp_db):
        """Test update with no valid fields does nothing."""
        patient_id = database.create_patient(first_name="John")

        database.update_patient(patient_id)

        patient = database.get_patient(patient_id)
        assert patient['first_name'] == "John"


class TestConditions:
    """Tests for condition management."""

    def test_add_condition_new(self, temp_db):
        """Test adding a new condition."""
        patient_id = database.create_patient()
        condition_id = database.add_condition(
            patient_id,
            name="Hypertension",
            status="stable",
            comment="Diagnosed 2 years ago"
        )

        assert condition_id > 0

        conditions = database.get_patient_conditions(patient_id)
        assert len(conditions) == 1
        assert conditions[0]['name'] == "Hypertension"
        assert conditions[0]['status'] == "stable"
        assert conditions[0]['comment'] == "Diagnosed 2 years ago"

    def test_add_condition_duplicate_updates(self, temp_db):
        """Test that adding duplicate condition updates existing one."""
        patient_id = database.create_patient()

        # Add initial condition
        id1 = database.add_condition(patient_id, name="Diabetes")

        # Add same condition with additional info
        id2 = database.add_condition(
            patient_id,
            name="diabetes",  # Case insensitive
            status="improving",
            comment="Well controlled"
        )

        # Should return same ID (updated, not created new)
        assert id1 == id2

        conditions = database.get_patient_conditions(patient_id)
        assert len(conditions) == 1
        assert conditions[0]['status'] == "improving"
        assert conditions[0]['comment'] == "Well controlled"

    def test_add_condition_case_insensitive(self, temp_db):
        """Test that condition names are case insensitive."""
        patient_id = database.create_patient()

        id1 = database.add_condition(patient_id, name="Hypertension")
        id2 = database.add_condition(patient_id, name="HYPERTENSION")

        assert id1 == id2

        conditions = database.get_patient_conditions(patient_id)
        assert len(conditions) == 1

    def test_get_patient_conditions_empty(self, temp_db):
        """Test getting conditions when patient has none."""
        patient_id = database.create_patient()
        conditions = database.get_patient_conditions(patient_id)
        assert conditions == []

    def test_get_patient_conditions_multiple(self, temp_db):
        """Test getting multiple conditions for a patient."""
        patient_id = database.create_patient()

        database.add_condition(patient_id, "Hypertension")
        database.add_condition(patient_id, "Diabetes")
        database.add_condition(patient_id, "Asthma")

        conditions = database.get_patient_conditions(patient_id)
        assert len(conditions) == 3


class TestMedications:
    """Tests for medication management."""

    def test_add_medication_full(self, temp_db):
        """Test adding a medication with all fields."""
        patient_id = database.create_patient()
        med_id = database.add_medication(
            patient_id,
            name="Lisinopril",
            dose="10mg",
            form="tablet",
            sig="once daily",
            indications="blood pressure"
        )

        assert med_id > 0

        medications = database.get_patient_medications(patient_id)
        assert len(medications) == 1
        assert medications[0]['name'] == "Lisinopril"
        assert medications[0]['dose'] == "10mg"
        assert medications[0]['form'] == "tablet"

    def test_add_medication_minimal(self, temp_db):
        """Test adding a medication with only name."""
        patient_id = database.create_patient()
        med_id = database.add_medication(patient_id, name="Aspirin")

        assert med_id > 0

        medications = database.get_patient_medications(patient_id)
        assert len(medications) == 1
        assert medications[0]['name'] == "Aspirin"

    def test_add_medication_duplicate_updates(self, temp_db):
        """Test that duplicate medication updates existing one."""
        patient_id = database.create_patient()

        id1 = database.add_medication(patient_id, name="Metformin")
        id2 = database.add_medication(
            patient_id,
            name="metformin",  # Case insensitive
            dose="500mg",
            form="tablet"
        )

        assert id1 == id2

        medications = database.get_patient_medications(patient_id)
        assert len(medications) == 1
        assert medications[0]['dose'] == "500mg"

    def test_get_patient_medications_empty(self, temp_db):
        """Test getting medications when patient has none."""
        patient_id = database.create_patient()
        medications = database.get_patient_medications(patient_id)
        assert medications == []


class TestAllergies:
    """Tests for allergy management."""

    def test_add_allergy_with_comment(self, temp_db):
        """Test adding an allergy with a comment."""
        patient_id = database.create_patient()
        allergy_id = database.add_allergy(
            patient_id,
            name="Penicillin",
            comment="Rash and hives"
        )

        assert allergy_id > 0

        allergies = database.get_patient_allergies(patient_id)
        assert len(allergies) == 1
        assert allergies[0]['name'] == "Penicillin"
        assert allergies[0]['comment'] == "Rash and hives"

    def test_add_allergy_without_comment(self, temp_db):
        """Test adding an allergy without a comment."""
        patient_id = database.create_patient()
        allergy_id = database.add_allergy(patient_id, name="Peanuts")

        assert allergy_id > 0

        allergies = database.get_patient_allergies(patient_id)
        assert len(allergies) == 1
        assert allergies[0]['name'] == "Peanuts"

    def test_add_allergy_duplicate_updates(self, temp_db):
        """Test that duplicate allergy updates existing one."""
        patient_id = database.create_patient()

        id1 = database.add_allergy(patient_id, name="Shellfish")
        id2 = database.add_allergy(
            patient_id,
            name="SHELLFISH",
            comment="Anaphylaxis risk"
        )

        assert id1 == id2

        allergies = database.get_patient_allergies(patient_id)
        assert len(allergies) == 1
        assert allergies[0]['comment'] == "Anaphylaxis risk"

    def test_get_patient_allergies_empty(self, temp_db):
        """Test getting allergies when patient has none."""
        patient_id = database.create_patient()
        allergies = database.get_patient_allergies(patient_id)
        assert allergies == []


class TestGoals:
    """Tests for goal management."""

    def test_add_goal_with_comment(self, temp_db):
        """Test adding a goal with a comment."""
        patient_id = database.create_patient()
        goal_id = database.add_goal(
            patient_id,
            name="Lower blood pressure",
            comment="Target 120/80"
        )

        assert goal_id > 0

        goals = database.get_patient_goals(patient_id)
        assert len(goals) == 1
        assert goals[0]['name'] == "Lower blood pressure"
        assert goals[0]['comment'] == "Target 120/80"

    def test_add_goal_without_comment(self, temp_db):
        """Test adding a goal without a comment."""
        patient_id = database.create_patient()
        goal_id = database.add_goal(patient_id, name="Lose weight")

        assert goal_id > 0

        goals = database.get_patient_goals(patient_id)
        assert len(goals) == 1
        assert goals[0]['name'] == "Lose weight"

    def test_add_goal_duplicate_updates(self, temp_db):
        """Test that duplicate goal updates existing one."""
        patient_id = database.create_patient()

        id1 = database.add_goal(patient_id, name="Exercise more")
        id2 = database.add_goal(
            patient_id,
            name="exercise more",
            comment="30 minutes daily"
        )

        assert id1 == id2

        goals = database.get_patient_goals(patient_id)
        assert len(goals) == 1
        assert goals[0]['comment'] == "30 minutes daily"

    def test_get_patient_goals_empty(self, temp_db):
        """Test getting goals when patient has none."""
        patient_id = database.create_patient()
        goals = database.get_patient_goals(patient_id)
        assert goals == []


class TestMessages:
    """Tests for message management."""

    def test_add_message_patient(self, temp_db):
        """Test adding a patient message."""
        patient_id = database.create_patient()
        message_id = database.add_message(
            patient_id,
            participant="patient",
            content="Hello, I need help"
        )

        assert message_id > 0

        messages = database.get_patient_messages(patient_id)
        assert len(messages) == 1
        assert messages[0]['participant'] == "patient"
        assert messages[0]['content'] == "Hello, I need help"

    def test_add_message_agent(self, temp_db):
        """Test adding an agent message."""
        patient_id = database.create_patient()
        message_id = database.add_message(
            patient_id,
            participant="agent",
            content="How can I help you today?"
        )

        assert message_id > 0

        messages = database.get_patient_messages(patient_id)
        assert len(messages) == 1
        assert messages[0]['participant'] == "agent"

    def test_get_patient_messages_chronological(self, temp_db):
        """Test that messages are returned in chronological order."""
        patient_id = database.create_patient()

        database.add_message(patient_id, "agent", "Hello")
        database.add_message(patient_id, "patient", "Hi")
        database.add_message(patient_id, "agent", "How can I help?")

        messages = database.get_patient_messages(patient_id)
        assert len(messages) == 3
        assert messages[0]['content'] == "Hello"
        assert messages[1]['content'] == "Hi"
        assert messages[2]['content'] == "How can I help?"

    def test_get_patient_messages_empty(self, temp_db):
        """Test getting messages when patient has none."""
        patient_id = database.create_patient()
        messages = database.get_patient_messages(patient_id)
        assert messages == []


class TestPatientCompleteness:
    """Tests for patient completeness calculation."""

    def test_completeness_empty_patient(self, temp_db):
        """Test completeness for a newly created patient."""
        patient_id = database.create_patient()
        completeness = database.get_patient_completeness(patient_id)

        # Demographics evaluates to None when all fields are None
        assert not completeness['demographics']
        assert completeness['concerns'] is False
        assert completeness['conditions'] is False
        assert completeness['medications'] is False
        assert completeness['allergies'] is False
        assert completeness['goals'] is False

    def test_completeness_full_demographics(self, temp_db):
        """Test completeness with complete demographics."""
        patient_id = database.create_patient(
            first_name="John",
            last_name="Doe",
            date_of_birth="1990-01-01",
            sex="male"
        )
        completeness = database.get_patient_completeness(patient_id)

        # Should evaluate to truthy (returns the sex/gender value)
        assert completeness['demographics']

    def test_completeness_partial_demographics(self, temp_db):
        """Test completeness with partial demographics."""
        patient_id = database.create_patient(
            first_name="John",
            last_name="Doe"
            # Missing DOB and sex/gender
        )
        completeness = database.get_patient_completeness(patient_id)

        # Should be falsy (evaluates to None or False)
        assert not completeness['demographics']

    def test_completeness_with_health_concerns(self, temp_db):
        """Test completeness with health concerns."""
        patient_id = database.create_patient(
            current_health_concerns="High blood pressure"
        )
        completeness = database.get_patient_completeness(patient_id)

        assert completeness['concerns'] is True

    def test_completeness_with_medical_data(self, temp_db):
        """Test completeness with various medical data."""
        patient_id = database.create_patient()

        database.add_condition(patient_id, "Hypertension")
        database.add_medication(patient_id, "Lisinopril")
        database.add_allergy(patient_id, "Penicillin")
        database.add_goal(patient_id, "Lower BP")

        completeness = database.get_patient_completeness(patient_id)

        assert completeness['conditions'] is True
        assert completeness['medications'] is True
        assert completeness['allergies'] is True
        assert completeness['goals'] is True

    def test_completeness_nonexistent_patient(self, temp_db):
        """Test completeness for non-existent patient."""
        completeness = database.get_patient_completeness(9999)

        assert completeness['demographics'] is False
        assert completeness['concerns'] is False
        assert completeness['conditions'] is False
        assert completeness['medications'] is False
        assert completeness['allergies'] is False
        assert completeness['goals'] is False


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_full_patient_workflow(self, temp_db):
        """Test a complete patient intake workflow."""
        # Create patient
        patient_id = database.create_patient(
            first_name="Alice",
            last_name="Johnson"
        )

        # Add messages
        database.add_message(patient_id, "agent", "Hello!")
        database.add_message(patient_id, "patient", "Hi, I'm Alice")

        # Update demographics
        database.update_patient(
            patient_id,
            date_of_birth="1985-03-15",
            sex="female"
        )

        # Add medical information
        database.add_condition(patient_id, "Type 2 Diabetes", status="stable")
        database.add_medication(patient_id, "Metformin", dose="500mg")
        database.add_allergy(patient_id, "Sulfa drugs", comment="Rash")
        database.add_goal(patient_id, "Better glucose control")

        # Verify everything
        patient = database.get_patient(patient_id)
        assert patient['first_name'] == "Alice"
        assert patient['date_of_birth'] == "1985-03-15"

        messages = database.get_patient_messages(patient_id)
        assert len(messages) == 2

        conditions = database.get_patient_conditions(patient_id)
        assert len(conditions) == 1

        completeness = database.get_patient_completeness(patient_id)
        assert completeness['demographics']  # Truthy
        assert completeness['conditions'] is True
        assert completeness['medications'] is True
        assert completeness['allergies'] is True
        assert completeness['goals'] is True

    def test_multiple_patients_isolated(self, temp_db):
        """Test that data for different patients is properly isolated."""
        # Create two patients
        patient1_id = database.create_patient(first_name="John")
        patient2_id = database.create_patient(first_name="Jane")

        # Add data to each
        database.add_condition(patient1_id, "Hypertension")
        database.add_condition(patient2_id, "Diabetes")

        # Verify isolation
        p1_conditions = database.get_patient_conditions(patient1_id)
        p2_conditions = database.get_patient_conditions(patient2_id)

        assert len(p1_conditions) == 1
        assert len(p2_conditions) == 1
        assert p1_conditions[0]['name'] == "Hypertension"
        assert p2_conditions[0]['name'] == "Diabetes"
