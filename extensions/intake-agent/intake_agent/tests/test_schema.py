"""Tests for the intake session validation."""

import json
import os

import pytest

from intake_agent.api.session import validate_session_data


class TestIntakeSessionSchema:
    """Tests for intake session validation."""

    def test_schema_file_exists_and_is_valid_json(self):
        """Test that the schema file exists and is valid JSON."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(
            current_dir, "..", "intake_agent", "schemas", "intake_session.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        # If we got here, the JSON is valid
        assert isinstance(schema, dict)
        assert "$schema" in schema

    def test_valid_session_data_passes_validation(self):
        """Test that valid session data passes validation."""
        valid_session = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [
                {
                    "role": "agent",
                    "content": "Hello!",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ],
            "collected_data": {
                "reason_for_visit": "Annual checkup",
                "reason_in_scope": True,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": "555-1234",
                "first_name": "John",
                "last_name": "Doe",
                "date_of_birth": "1990-01-01",
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "active",
        }

        # Should not raise an exception
        validate_session_data(valid_session)

    def test_invalid_session_id_fails_validation(self):
        """Test that invalid session ID format fails validation."""
        invalid_session = {
            "session_id": "invalid-id",  # Not 32-char hex
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [],
            "collected_data": {
                "reason_for_visit": None,
                "reason_in_scope": None,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": None,
                "first_name": None,
                "last_name": None,
                "date_of_birth": None,
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "active",
        }

        with pytest.raises(ValueError, match="Invalid session_id format"):
            validate_session_data(invalid_session)

    def test_missing_required_field_fails_validation(self):
        """Test that missing required fields fail validation."""
        incomplete_session = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            # Missing updated_at, messages, collected_data, status
        }

        with pytest.raises(ValueError, match="Missing required field"):
            validate_session_data(incomplete_session)

    def test_invalid_message_role_fails_validation(self):
        """Test that invalid message role fails validation."""
        invalid_session = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [
                {
                    "role": "invalid_role",  # Not 'agent' or 'user'
                    "content": "Hello!",
                    "timestamp": "2025-01-01T00:00:00Z",
                }
            ],
            "collected_data": {
                "reason_for_visit": None,
                "reason_in_scope": None,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": None,
                "first_name": None,
                "last_name": None,
                "date_of_birth": None,
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "active",
        }

        with pytest.raises(ValueError, match="Invalid message role"):
            validate_session_data(invalid_session)

    def test_invalid_status_fails_validation(self):
        """Test that invalid status fails validation."""
        invalid_session = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [],
            "collected_data": {
                "reason_for_visit": None,
                "reason_in_scope": None,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": None,
                "first_name": None,
                "last_name": None,
                "date_of_birth": None,
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "invalid_status",  # Not in enum
        }

        with pytest.raises(ValueError, match="Invalid status"):
            validate_session_data(invalid_session)

    def test_invalid_date_of_birth_format_fails_validation(self):
        """Test that invalid date_of_birth format fails validation."""
        invalid_session = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [],
            "collected_data": {
                "reason_for_visit": None,
                "reason_in_scope": None,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": None,
                "first_name": None,
                "last_name": None,
                "date_of_birth": "01/01/1990",  # Wrong format
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "active",
        }

        with pytest.raises(ValueError, match="Invalid date_of_birth format"):
            validate_session_data(invalid_session)

    def test_null_values_allowed_in_collected_data(self):
        """Test that null values are allowed in collected_data fields."""
        session_with_nulls = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [],
            "collected_data": {
                "reason_for_visit": None,
                "reason_in_scope": None,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": None,
                "first_name": None,
                "last_name": None,
                "date_of_birth": None,
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "active",
        }

        # Should not raise an exception
        validate_session_data(session_with_nulls)

    def test_additional_properties_allowed_but_ignored(self):
        """Test that additional properties don't cause validation errors (we don't strictly enforce this)."""
        session_with_extra = {
            "session_id": "a1b2c3d4e5f67890a1b2c3d4e5f67890",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [],
            "collected_data": {
                "reason_for_visit": None,
                "reason_in_scope": None,
                "proposed_appointment_times": None,
                "selected_appointment_time": None,
                "selected_appointment_index": None,
                "phone": None,
                "first_name": None,
                "last_name": None,
                "date_of_birth": None,
                "policy_agreement_accepted": None,
                "patient_mrn": None,
            },
            "status": "active",
            "extra_field": "allowed but ignored",  # Additional property
        }

        # Our custom validation doesn't strictly enforce no additional properties
        # This is acceptable as we validate required fields and types
        validate_session_data(session_with_extra)
