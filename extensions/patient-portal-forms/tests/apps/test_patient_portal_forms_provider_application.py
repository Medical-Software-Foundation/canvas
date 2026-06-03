"""Tests for PatientPortalFormsProviderApplication."""

import json
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType

from patient_portal_forms.apps.patient_portal_forms_provider_application import (
    PatientPortalFormsProviderApplication,
)


def test_on_open_launches_modal_with_correct_url():
    """Test that on_open launches a modal with the correct URL."""
    # Create mock event
    mock_event = MagicMock()
    mock_event.context = {
        "patient": {
            "id": "patient-123"
        }
    }

    # Instantiate the application
    app = PatientPortalFormsProviderApplication(event=mock_event)

    # Call on_open
    result = app.on_open()

    # Assert that result is a list
    assert isinstance(result, list)
    assert len(result) == 1

    # Assert the effect type is correct
    assert result[0].type == EffectType.LAUNCH_MODAL

    # Parse the payload
    payload_data = json.loads(result[0].payload)

    # Assert the URL contains the correct patient ID
    expected_url = "/plugin-io/api/patient_portal_forms/provider-view/patient/patient-123"
    assert payload_data["data"]["url"] == expected_url

    # Assert the target is right_chart_pane_large
    assert payload_data["data"]["target"] == "right_chart_pane_large"


def test_on_open_with_different_patient_id():
    """Test that on_open works with different patient IDs."""
    # Create mock event with different patient ID
    mock_event = MagicMock()
    mock_event.context = {
        "patient": {
            "id": "patient-456"
        }
    }

    # Instantiate the application
    app = PatientPortalFormsProviderApplication(event=mock_event)

    # Call on_open
    result = app.on_open()

    # Parse the payload
    payload_data = json.loads(result[0].payload)

    # Assert the URL contains the new patient ID
    expected_url = "/plugin-io/api/patient_portal_forms/provider-view/patient/patient-456"
    assert payload_data["data"]["url"] == expected_url


def test_on_open_returns_list_of_effects():
    """Test that on_open returns a list of effects."""
    # Create mock event
    mock_event = MagicMock()
    mock_event.context = {
        "patient": {
            "id": "patient-789"
        }
    }

    # Instantiate the application
    app = PatientPortalFormsProviderApplication(event=mock_event)

    # Call on_open
    result = app.on_open()

    # Assert that result is a list
    assert isinstance(result, list)
    assert len(result) == 1

    # Assert the first item is the launch modal effect
    assert result[0].type == EffectType.LAUNCH_MODAL
