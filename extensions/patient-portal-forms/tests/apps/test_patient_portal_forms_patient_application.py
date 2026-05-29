"""Tests for PatientPortalFormsPatientApplication."""

import json
from unittest.mock import MagicMock

import pytest
from canvas_sdk.effects import EffectType

from patient_portal_forms.apps.patient_portal_forms_patient_application import (
    PatientPortalFormsPatientApplication,
)


def test_on_open_launches_modal_with_correct_url():
    """Test that on_open launches a modal with the correct URL for patient view."""
    # Create mock event
    mock_event = MagicMock()
    mock_event.context = {
        "user": {
            "id": "user-123"
        }
    }

    # Instantiate the application
    app = PatientPortalFormsPatientApplication(event=mock_event)

    # Call on_open
    result = app.on_open()

    # Assert the effect type is correct
    assert result.type == EffectType.LAUNCH_MODAL

    # Parse the payload
    payload_data = json.loads(result.payload)

    # Assert the URL contains the correct user ID
    expected_url = "/plugin-io/api/patient_portal_forms/patient-view/patient/user-123"
    assert payload_data["data"]["url"] == expected_url

    # Assert the target is page (full page modal)
    assert payload_data["data"]["target"] == "page"


def test_on_open_with_different_user_id():
    """Test that on_open works with different user IDs."""
    # Create mock event with different user ID
    mock_event = MagicMock()
    mock_event.context = {
        "user": {
            "id": "user-456"
        }
    }

    # Instantiate the application
    app = PatientPortalFormsPatientApplication(event=mock_event)

    # Call on_open
    result = app.on_open()

    # Parse the payload
    payload_data = json.loads(result.payload)

    # Assert the URL contains the new user ID
    expected_url = "/plugin-io/api/patient_portal_forms/patient-view/patient/user-456"
    assert payload_data["data"]["url"] == expected_url
