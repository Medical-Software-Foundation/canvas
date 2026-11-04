"""Tests for consent_capture/handlers/consent_settings_app.py (the app drawer entry)."""

from types import SimpleNamespace
from unittest.mock import patch

from consent_capture.handlers.consent_settings_app import ConsentSettingsApp
from consent_capture.picker_modal import SETTINGS_URL

MODULE = "consent_capture.handlers.consent_settings_app"


def _app(context=None, secrets=None):
    app = ConsentSettingsApp()
    app.event = SimpleNamespace(context=context if context is not None else {"user": {"id": "staff-1", "type": "Staff"}})
    app.secrets = secrets if secrets is not None else {"CONSENT_ADMIN_USERS": "Lisa Bond"}
    return app


class TestIdentity:
    def test_drawer_entry_names_and_icon(self):
        assert ConsentSettingsApp.NAME == "Consent Settings"
        assert ConsentSettingsApp.IDENTIFIER == "consent_capture__settings"
        assert ConsentSettingsApp.ICON_URL == "/plugin-io/api/consent_capture/admin/icon.svg"


class TestVisible:
    def test_admin_sees_it(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=True) as mock_admin:
            assert _app().visible() is True
        mock_admin.assert_called_once_with("staff-1", "Lisa Bond")

    def test_other_staff_do_not(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=False):
            assert _app().visible() is False

    def test_staff_key_is_accepted(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=True) as mock_admin:
            _app(context={"staff": {"id": "staff-2"}}).visible()
        mock_admin.assert_called_once_with("staff-2", "Lisa Bond")

    def test_non_staff_user_gets_no_id(self):
        with patch(f"{MODULE}.is_consent_admin", return_value=False) as mock_admin:
            assert _app(context={"user": {"id": "p1", "type": "Patient"}}).visible() is False
        mock_admin.assert_called_once_with(None, "Lisa Bond")

    def test_missing_context_and_secrets(self):
        app = ConsentSettingsApp()
        app.event = SimpleNamespace(context=None)
        app.secrets = None
        with patch(f"{MODULE}.is_consent_admin", return_value=False) as mock_admin:
            assert app.visible() is False
        mock_admin.assert_called_once_with(None, "")


class TestOnOpen:
    def test_opens_the_settings_page(self):
        effect = _app().on_open()
        assert effect["type"] == "LaunchModalEffect"
        assert effect["url"] == SETTINGS_URL
        assert effect["target"] == "page"
