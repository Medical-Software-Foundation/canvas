"""Smoke tests: foundation modules import and basic behavior holds under SDK 0.154."""

from unittest.mock import MagicMock

import pytest

from portal_content.content_types import documents
from portal_content.shared import config


def test_config_defaults_all_enabled(mock_secrets):
    enabled = config.get_enabled_components(mock_secrets)
    assert enabled == {"imaging", "labs", "visits", "letters"}


def test_config_unknown_component_ignored():
    enabled = config.get_enabled_components({"ENABLED_COMPONENTS": "labs,bogus"})
    assert enabled == {"labs"}


def test_visits_config_fails_closed_without_note_types():
    with pytest.raises(config.ConfigurationError):
        config.validate_visits_configuration({"NOTE_TYPES": ""})


def test_documents_category_map_covers_all_components():
    assert set(documents.CATEGORY_CODES) == {"labs", "imaging", "letters"}
    assert documents.CATEGORY_CODES["labs"] == "labreport"


def test_applications_launch_expected_pages():
    from portal_content.applications.records_app import RecordsApp
    from portal_content.applications.profile_app import ProfileApp

    for app_cls, route in (
        (RecordsApp, "/app/records"),
        (ProfileApp, "/app/profile"),
    ):
        app = app_cls(event=MagicMock())
        effect = app.on_open()
        assert "/plugin-io/api/portal_content" + route in effect.payload


def test_hold_unreviewed_results_flag():
    assert config.hold_unreviewed_results({"HOLD_UNREVIEWED_RESULTS": "true"}) is True
    assert config.hold_unreviewed_results({"HOLD_UNREVIEWED_RESULTS": "On"}) is True
    assert config.hold_unreviewed_results({"HOLD_UNREVIEWED_RESULTS": "false"}) is False
    assert config.hold_unreviewed_results({}) is False
