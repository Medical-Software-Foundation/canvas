"""Tests for consent_capture/handlers/consent_app.py."""

from unittest.mock import MagicMock, patch

from consent_capture.handlers.consent_app import ConsentApp

MODULE = "consent_capture.handlers.consent_app"


def _app(context=None, secrets=None):
    app = ConsentApp()
    if context is not None:
        app.context = context
    if secrets is not None:
        app.secrets = secrets
    return app


class TestOnOpen:
    def test_opens_picker_for_charted_patient(self):
        app = _app(
            context={"patient": {"id": "patient-7"}, "user": {"id": "staff-3"}},
            secrets={"CONSENT_ADMIN_USERS": "jane"},
        )
        modal = MagicMock()
        modal.apply.return_value = "EFFECT"
        with patch(f"{MODULE}.build_picker_modal", return_value=modal) as mbuild:
            result = app.on_open()
            mbuild.assert_called_once_with("patient-7", "staff-3", {"CONSENT_ADMIN_USERS": "jane"})
        assert result == "EFFECT"

    def test_missing_context_uses_empty_ids_and_secrets(self):
        app = ConsentApp()  # no context, no secrets attributes
        modal = MagicMock()
        modal.apply.return_value = "E"
        with patch(f"{MODULE}.build_picker_modal", return_value=modal) as mbuild:
            app.on_open()
            mbuild.assert_called_once_with("", "", {})

    def test_partial_context_without_user(self):
        app = _app(context={"patient": {"id": "p9"}})  # patient but no user
        modal = MagicMock()
        modal.apply.return_value = "E"
        with patch(f"{MODULE}.build_picker_modal", return_value=modal) as mbuild:
            app.on_open()
            mbuild.assert_called_once_with("p9", "", {})
