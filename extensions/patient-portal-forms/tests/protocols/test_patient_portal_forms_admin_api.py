"""Tests for PatientPortalFormsAdminAPI.

Exercises the migration endpoint that walks legacy `portal_forms`
PatientMetadata into the new QuestionnaireAssignment model.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType
from http import HTTPStatus

from patient_portal_forms.protocols.patient_portal_forms_admin_api import (
    PatientPortalFormsAdminAPI,
)


def _api(*, enabled: bool = True) -> PatientPortalFormsAdminAPI:
    api = PatientPortalFormsAdminAPI.__new__(PatientPortalFormsAdminAPI)
    api.request = MagicMock()
    api.event = MagicMock()
    # Fail-closed gate: the migration admin is only active when the secret
    # is explicitly set. Tests that need the disabled path pass enabled=False.
    api.secrets = {"ENABLE_MIGRATION_ADMIN": "1"} if enabled else {}
    return api


def test_admin_landing_returns_html_when_enabled():
    api = _api()
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.render_to_string",
        return_value="<html>admin</html>",
    ), patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.HTMLResponse"
    ) as mock_html:
        mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
        result = api.admin_landing()
    assert len(result) == 1
    assert mock_html.call_args.kwargs["status_code"] == HTTPStatus.OK


def test_admin_landing_returns_disabled_page_when_secret_missing():
    """Fail-closed: missing secret means the admin is inert, not accessible."""
    api = _api(enabled=False)
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.render_to_string",
        return_value="<html>disabled</html>",
    ) as mock_render, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.HTMLResponse"
    ) as mock_html:
        mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
        result = api.admin_landing()

    assert len(result) == 1
    assert mock_html.call_args.kwargs["status_code"] == HTTPStatus.FORBIDDEN
    # Confirms it's the disabled template (not the regular migration template)
    rendered_template = mock_render.call_args.args[0]
    assert "disabled" in rendered_template


def test_admin_landing_treats_empty_secret_as_disabled():
    """Whitespace-only strings count as unset — strict fail-closed semantics."""
    api = _api()
    api.secrets = {"ENABLE_MIGRATION_ADMIN": "   "}
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.render_to_string",
        return_value="<html>disabled</html>",
    ), patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.HTMLResponse"
    ) as mock_html:
        mock_html.return_value = MagicMock(type=EffectType.SIMPLE_API_RESPONSE)
        api.admin_landing()
    assert mock_html.call_args.kwargs["status_code"] == HTTPStatus.FORBIDDEN


def test_migrate_metadata_rejects_when_disabled():
    api = _api(enabled=False)
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadata.objects"
    ) as mock_pm, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.QuestionnaireAssignmentService"
    ) as mock_service, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.JSONResponse"
    ) as mock_json_cls:
        captured = {}

        def capture(payload, status_code):
            captured["payload"] = payload
            captured["status_code"] = status_code
            return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

        mock_json_cls.side_effect = capture
        api.migrate_metadata()

    assert captured["status_code"] == HTTPStatus.FORBIDDEN
    # Defense-in-depth: even direct URL access must not touch the DB
    mock_pm.filter.assert_not_called()
    mock_service.migrate_from_metadata.assert_not_called()


def test_clear_legacy_metadata_rejects_when_disabled():
    api = _api(enabled=False)
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadata.objects"
    ) as mock_pm, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadataEffect"
    ) as mock_effect_cls, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.JSONResponse"
    ) as mock_json_cls:
        captured = {}

        def capture(payload, status_code):
            captured["status_code"] = status_code
            return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

        mock_json_cls.side_effect = capture
        api.clear_legacy_metadata()

    assert captured["status_code"] == HTTPStatus.FORBIDDEN
    mock_pm.filter.assert_not_called()
    mock_effect_cls.assert_not_called()


def test_migrate_metadata_aggregates_service_results():
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())

    api = _api()
    rows = [
        (pid_a, json.dumps({"questionnaires": [{"questionnaire_name": "PHQ-9"}]})),
        (pid_b, json.dumps({"questionnaires": []})),
    ]
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadata.objects"
    ) as mock_pm, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.QuestionnaireAssignmentService"
    ) as mock_service, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.JSONResponse"
    ) as mock_json_cls:
        mock_pm.filter.return_value.values_list.return_value.iterator.return_value = rows
        mock_service.migrate_from_metadata.side_effect = [
            {"created": 1, "skipped": 0, "errors": []},
            {"created": 0, "skipped": 0, "errors": []},
        ]
        captured = {}

        def capture(payload, status_code):
            captured["payload"] = payload
            captured["status_code"] = status_code
            return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

        mock_json_cls.side_effect = capture
        api.migrate_metadata()

    assert captured["status_code"] == HTTPStatus.OK
    assert captured["payload"]["patients_processed"] == 2
    assert captured["payload"]["rows_created"] == 1
    assert captured["payload"]["rows_skipped"] == 0
    assert captured["payload"]["errors"] == []
    assert mock_service.migrate_from_metadata.call_count == 2


def test_clear_legacy_metadata_emits_one_upsert_effect_per_patient():
    """Plugins can't delete PatientMetadata rows — the SDK only exposes
    upsert. The endpoint emits an empty-value upsert for each affected
    patient as the closest available "clear" operation."""
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())
    api = _api()

    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadata.objects"
    ) as mock_pm, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadataEffect"
    ) as mock_effect_cls, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.JSONResponse"
    ) as mock_json_cls:
        mock_pm.filter.return_value.exclude.return_value.values_list.return_value = [
            pid_a,
            pid_b,
        ]
        upsert_effect = MagicMock(type=EffectType.UPSERT_PATIENT_METADATA)
        mock_effect_cls.return_value.upsert.return_value = upsert_effect
        captured = {}

        def capture(payload, status_code):
            captured["payload"] = payload
            captured["status_code"] = status_code
            return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

        mock_json_cls.side_effect = capture
        result = api.clear_legacy_metadata()

    # Filter to portal_forms only — never touch unrelated metadata.
    mock_pm.filter.assert_called_once_with(key="portal_forms")
    # Already-empty rows are skipped to keep the response count meaningful.
    mock_pm.filter.return_value.exclude.assert_called_once_with(value="")
    # One PatientMetadataEffect per patient, each with key=portal_forms,
    # upserted with an empty string.
    assert mock_effect_cls.call_count == 2
    for call_args in mock_effect_cls.call_args_list:
        assert call_args.kwargs["key"] == "portal_forms"
    for upsert_call in mock_effect_cls.return_value.upsert.call_args_list:
        assert upsert_call.args == ("",)

    # Response shape
    assert captured["status_code"] == HTTPStatus.OK
    assert captured["payload"]["rows_cleared"] == 2
    # Returned list: 2 upserts + 1 JSON response
    assert len(result) == 3


def test_clear_legacy_metadata_returns_only_response_when_no_rows():
    api = _api()
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadata.objects"
    ) as mock_pm, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadataEffect"
    ) as mock_effect_cls, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.JSONResponse"
    ) as mock_json_cls:
        mock_pm.filter.return_value.exclude.return_value.values_list.return_value = []
        captured = {}

        def capture(payload, status_code):
            captured["payload"] = payload
            return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

        mock_json_cls.side_effect = capture
        result = api.clear_legacy_metadata()
    assert captured["payload"]["rows_cleared"] == 0
    assert mock_effect_cls.call_count == 0
    assert len(result) == 1


def test_migrate_metadata_collects_errors_and_skips_invalid_json():
    pid = str(uuid.uuid4())
    api = _api()

    rows = [(pid, "{not json}"), (pid, "")]
    with patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.PatientMetadata.objects"
    ) as mock_pm, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.QuestionnaireAssignmentService"
    ) as mock_service, patch(
        "patient_portal_forms.protocols.patient_portal_forms_admin_api.JSONResponse"
    ) as mock_json_cls:
        mock_pm.filter.return_value.values_list.return_value.iterator.return_value = rows
        captured = {}

        def capture(payload, status_code):
            captured["payload"] = payload
            return MagicMock(type=EffectType.SIMPLE_API_RESPONSE)

        mock_json_cls.side_effect = capture
        api.migrate_metadata()

    # Invalid JSON is reported; empty value is processed-but-skipped silently.
    # The service is not called for either of these rows.
    mock_service.migrate_from_metadata.assert_not_called()
    assert captured["payload"]["patients_processed"] == 2
    assert any("invalid JSON" in e for e in captured["payload"]["errors"])
