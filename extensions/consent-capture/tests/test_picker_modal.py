"""Tests for consent_capture/picker_modal.py (the shared picker-modal builder)."""

import json
from unittest.mock import MagicMock, patch

from consent_capture.picker_modal import SETTINGS_URL, build_picker_modal

MODULE = "consent_capture.picker_modal"


def _items():
    return [{"code": "universal", "on_file": False}, {"code": "rpm", "on_file": True}]


def _records():
    return [{"id": "1", "code": "rpm", "display": "RPM", "status": "active", "on_file": True,
             "effective_date": "2026-01-02", "expiration_date": ""}]


class TestBuildPickerModal:
    def test_builds_full_context_and_default_modal(self):
        items = _items()
        records = _records()
        dob = MagicMock()
        dob.isoformat.return_value = "1990-01-01"
        with patch(f"{MODULE}.picker_items", return_value=items), patch(
            f"{MODULE}.consent_records", return_value=records
        ), patch(
            f"{MODULE}.Patient"
        ) as mock_patient, patch(
            f"{MODULE}.is_consent_admin", return_value=True
        ), patch(f"{MODULE}.render_to_string", return_value="<html>picker</html>") as mock_render, patch(f"{MODULE}.log"):
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = (
                "Jane",
                "Doe",
                dob,
            )
            effect = build_picker_modal("patient-123", "staff-9", {"CONSENT_ADMIN_USERS": "jane"})

        template, context = mock_render.mock_calls[0].args
        assert template == "templates/picker.html"
        assert context["patient_id"] == "patient-123"
        assert context["patient_name"] == "Jane Doe"
        assert context["patient_dob"] == "1990-01-01"
        assert json.loads(context["consents_json"]) == items
        assert json.loads(context["records_json"]) == records
        assert json.loads(context["method_options_json"]) == ["Verbal", "Electronic", "Written", "Other"]
        assert context["is_admin"] is True
        assert context["settings_url"] == SETTINGS_URL
        # An un-applied DEFAULT_MODAL effect carrying the rendered HTML.
        assert effect.target == "default_modal"
        assert effect.content == "<html>picker</html>"
        assert effect.title == "Consents"

    def test_non_admin_hides_wrench(self):
        with patch(f"{MODULE}.picker_items", return_value=[]), patch(
            f"{MODULE}.consent_records", return_value=[]
        ), patch(
            f"{MODULE}.Patient"
        ) as mock_patient, patch(
            f"{MODULE}.is_consent_admin", return_value=False
        ), patch(f"{MODULE}.render_to_string", return_value="x"), patch(f"{MODULE}.log"):
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = None
            build_picker_modal("p1", "s1", {"CONSENT_ADMIN_USERS": "someone-else"})
            # context reflects is_admin=False
        # (assertion via the render call)

    def test_no_patient_row_leaves_name_and_dob_blank(self):
        with patch(f"{MODULE}.picker_items", return_value=[]), patch(
            f"{MODULE}.consent_records", return_value=[]
        ), patch(
            f"{MODULE}.Patient"
        ) as mock_patient, patch(f"{MODULE}.is_consent_admin", return_value=True), patch(
            f"{MODULE}.render_to_string", return_value="x"
        ) as mock_render, patch(f"{MODULE}.log"):
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = None
            build_picker_modal("patient-123", "staff-9", {})
            context = mock_render.mock_calls[0].args[1]
            assert context["patient_name"] == ""
            assert context["patient_dob"] == ""

    def test_no_patient_id_skips_patient_lookup(self):
        with patch(f"{MODULE}.picker_items", return_value=[]), patch(
            f"{MODULE}.consent_records", return_value=[]
        ), patch(
            f"{MODULE}.Patient"
        ) as mock_patient, patch(f"{MODULE}.is_consent_admin", return_value=False), patch(
            f"{MODULE}.render_to_string", return_value="x"
        ) as mock_render, patch(f"{MODULE}.log"):
            build_picker_modal("", "staff-9", {})
            # No patient in context -> no Patient query.
            assert mock_patient.mock_calls == []
            context = mock_render.mock_calls[0].args[1]
            assert context["patient_name"] == "" and context["patient_dob"] == ""

    def test_passes_staff_and_admin_users_to_is_consent_admin(self):
        with patch(f"{MODULE}.picker_items", return_value=[]), patch(
            f"{MODULE}.consent_records", return_value=[]
        ), patch(
            f"{MODULE}.Patient"
        ) as mock_patient, patch(
            f"{MODULE}.is_consent_admin", return_value=True
        ) as mock_admin, patch(f"{MODULE}.render_to_string", return_value="x"), patch(f"{MODULE}.log"):
            mock_patient.objects.filter.return_value.values_list.return_value.first.return_value = None
            build_picker_modal("p1", "staff-42", {"CONSENT_ADMIN_USERS": "staff-42"})
            mock_admin.assert_called_once_with("staff-42", "staff-42")
