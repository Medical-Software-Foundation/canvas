"""Tests for chart action buttons (Eligibility, Align, Unalign)."""
import pytest
from unittest.mock import MagicMock, call


def _make_button(cls, patient_id="patient-uuid-123"):
    mock_event = MagicMock()
    mock_event.context = {"patient": {"id": patient_id}} if patient_id else {}
    mock_event.target.id = patient_id or ""
    handler = cls(event=mock_event)
    return handler, mock_event


def _make_button_no_patient(cls):
    mock_event = MagicMock()
    mock_event.context = {}
    mock_event.target.id = ""
    handler = cls(event=mock_event)
    return handler, mock_event


class TestEligibilityActionButton:
    def test_handle_returns_launch_modal_with_patient_id(self):
        from cms_access_fhir_client.handlers.action_buttons import EligibilityActionButton
        handler, mock_event = _make_button(EligibilityActionButton, "p-123")
        effects = handler.handle()

        assert len(effects) == 1
        from canvas_sdk.effects.base import EffectType
        assert effects[0].type == EffectType.LAUNCH_MODAL

    def test_handle_returns_empty_when_no_patient_in_context(self):
        from cms_access_fhir_client.handlers.action_buttons import EligibilityActionButton
        handler, mock_event = _make_button_no_patient(EligibilityActionButton)
        effects = handler.handle()
        assert effects == []

    def test_button_key_is_unique_across_all_three_buttons(self):
        from cms_access_fhir_client.handlers.action_buttons import (
            EligibilityActionButton,
            AlignActionButton,
            UnalignActionButton,
        )
        keys = {
            EligibilityActionButton.BUTTON_KEY,
            AlignActionButton.BUTTON_KEY,
            UnalignActionButton.BUTTON_KEY,
        }
        assert len(keys) == 3, "All button keys must be unique"

    def test_all_buttons_at_chart_patient_header(self):
        from cms_access_fhir_client.handlers.action_buttons import (
            EligibilityActionButton,
            AlignActionButton,
            UnalignActionButton,
        )
        from canvas_sdk.handlers.action_button import ActionButton
        expected = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
        assert EligibilityActionButton.BUTTON_LOCATION == expected
        assert AlignActionButton.BUTTON_LOCATION == expected
        assert UnalignActionButton.BUTTON_LOCATION == expected


class TestAlignActionButton:
    def test_handle_returns_launch_modal(self):
        from cms_access_fhir_client.handlers.action_buttons import AlignActionButton
        handler, _ = _make_button(AlignActionButton, "p-456")
        effects = handler.handle()

        assert len(effects) == 1
        from canvas_sdk.effects.base import EffectType
        assert effects[0].type == EffectType.LAUNCH_MODAL

    def test_handle_returns_empty_when_no_patient(self):
        from cms_access_fhir_client.handlers.action_buttons import AlignActionButton
        handler, _ = _make_button_no_patient(AlignActionButton)
        effects = handler.handle()
        assert effects == []


class TestUnalignActionButton:
    def test_handle_returns_launch_modal(self):
        from cms_access_fhir_client.handlers.action_buttons import UnalignActionButton
        handler, _ = _make_button(UnalignActionButton, "p-789")
        effects = handler.handle()

        assert len(effects) == 1
        from canvas_sdk.effects.base import EffectType
        assert effects[0].type == EffectType.LAUNCH_MODAL

    def test_handle_returns_empty_when_no_patient(self):
        from cms_access_fhir_client.handlers.action_buttons import UnalignActionButton
        handler, _ = _make_button_no_patient(UnalignActionButton)
        effects = handler.handle()
        assert effects == []
