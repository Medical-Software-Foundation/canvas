"""Tests for consent_capture/handlers/consent_button.py."""

from unittest.mock import MagicMock, call, patch

from consent_capture.constants import (
    BUTTON_DUE_BACKGROUND,
    BUTTON_DUE_TEXT,
    BUTTON_SATISFIED_BACKGROUND,
    BUTTON_SATISFIED_TEXT,
)
from consent_capture.handlers.consent_button import ConsentButton, needs_any

MODULE = "consent_capture.handlers.consent_button"


def _assert_red(button):
    assert button.BUTTON_TITLE == "Consents"  # label is always "Consents"
    assert button.BUTTON_BACKGROUND_COLOR == BUTTON_DUE_BACKGROUND
    assert button.BUTTON_TEXT_COLOR == BUTTON_DUE_TEXT


def _assert_neutral(button):
    assert button.BUTTON_TITLE == "Consents"  # label is always "Consents"
    assert button.BUTTON_BACKGROUND_COLOR == BUTTON_SATISFIED_BACKGROUND
    assert button.BUTTON_TEXT_COLOR == BUTTON_SATISFIED_TEXT


def _item(code, on_file, required=True):
    return {
        "code": code,
        "system": "http://loinc.org",
        "display": code.title(),
        "paragraphs": ["Read this."],
        "method_enabled": True,
        "obtained_by_enabled": True,
        "capacity_enabled": True,
        "required": required,
        "on_file": on_file,
    }


class TestNeedsAny:
    def test_true_when_a_required_consent_not_on_file(self):
        assert needs_any([_item("a", True), _item("b", False)]) is True

    def test_false_when_all_on_file(self):
        assert needs_any([_item("a", True), _item("b", True)]) is False
        assert needs_any([_item("a", True)]) is False

    def test_false_when_only_optional_missing(self):
        # An optional consent that's not on file must NOT surface the red button.
        assert needs_any([_item("a", True), _item("b", False, required=False)]) is False
        assert needs_any([_item("b", False, required=False)]) is False

    def test_false_when_empty(self):
        assert needs_any([]) is False


class TestPatientId:
    def test_returns_target_id(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        assert button._patient_id() == "patient-123"

    def test_no_target_returns_none(self):
        button = ConsentButton()
        button.event = None
        assert button._patient_id() is None


class TestVisible:
    def _button(self):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        return button

    def test_no_patient_id_not_visible(self):
        button = ConsentButton()
        button.event = None
        assert button.visible() is False

    def test_red_when_a_required_consent_is_due(self):
        button = self._button()
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.picker_items", return_value=[_item("a", False)]
        ) as mock_items:
            assert button.visible() is True
            assert mock_items.mock_calls == [call("patient-123")]
        _assert_red(button)

    def test_neutral_when_all_on_file(self):
        button = self._button()
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.picker_items", return_value=[_item("a", True)]
        ):
            assert button.visible() is True
        _assert_neutral(button)

    def test_neutral_when_only_optional_missing(self):
        button = self._button()
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.picker_items", return_value=[_item("a", False, required=False)]
        ):
            assert button.visible() is True
        _assert_neutral(button)

    def test_neutral_when_no_consents_configured(self):
        button = self._button()
        with patch(f"{MODULE}.is_eligible_patient", return_value=True), patch(
            f"{MODULE}.picker_items", return_value=[]
        ):
            assert button.visible() is True
        _assert_neutral(button)

    def test_neutral_and_never_red_for_ineligible_patient(self):
        # Inactive/deceased patients still see the button, but it is always the
        # neutral gray chip and never red — even with a required consent missing.
        # Eligibility short-circuits before the consent lookup.
        button = self._button()
        with patch(f"{MODULE}.is_eligible_patient", return_value=False), patch(
            f"{MODULE}.picker_items", return_value=[_item("a", False)]
        ) as mock_items:
            assert button.visible() is True
        mock_items.assert_not_called()  # ineligibility short-circuits before the consent check
        _assert_neutral(button)


class TestHandle:
    """handle() delegates modal construction to the shared build_picker_modal;
    the modal's content is covered by tests/test_picker_modal.py."""

    def _button(self, context=None, secrets=None):
        button = ConsentButton()
        button.event = MagicMock()
        button.event.target.id = "patient-123"
        button.event.context = {"user": {"id": "staff-9"}} if context is None else context
        if secrets is not None:
            button.secrets = secrets
        return button

    def test_handle_delegates_to_build_picker_modal(self):
        button = self._button(secrets={"CONSENT_ADMIN_USERS": "jane"})
        effect = object()
        modal = MagicMock()
        modal.apply.return_value = effect
        with patch(f"{MODULE}.build_picker_modal", return_value=modal) as mbuild:
            result = button.handle()
            mbuild.assert_called_once_with("patient-123", "staff-9", {"CONSENT_ADMIN_USERS": "jane"})
        assert result == [effect]

    def test_handle_missing_user_context_uses_empty_staff(self):
        button = self._button(context={})
        modal = MagicMock()
        modal.apply.return_value = "eff"
        with patch(f"{MODULE}.build_picker_modal", return_value=modal) as mbuild:
            button.handle()
            # no user in context -> empty staff id; no secrets set -> empty dict
            mbuild.assert_called_once_with("patient-123", "", {})
