"""Tests for the CreateFaxSummaryAPI SimpleAPI route."""

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import ValidationError

from recent_labs.protocols.fax_summary_api import (
    RECENT_LABS_SCHEMA_KEY,
    CreateFaxSummaryAPI,
    build_fax_note_html,
    first_active_practice_location_id,
    resolve_note_type_id,
)


def _api(body, secrets, headers=None):
    api = MagicMock(spec=CreateFaxSummaryAPI)
    api.secrets = secrets
    api.request = MagicMock()
    api.request.json.return_value = body
    api.request.headers = headers if headers is not None else {"canvas-logged-in-user-id": "staff-1"}
    return api


class TestCreateFaxSummaryAPI:
    def test_missing_note_type_secret_returns_error(self):
        api = _api({"patient_id": "p1"}, secrets={})
        with patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "RECENT_LABS_NOTE_TYPE_ID" in str(result[0])

    def test_missing_patient_id_returns_error(self):
        api = _api({}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "nt-1"})
        with patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "Patient ID" in str(result[0])

    def test_null_body_returns_error(self):
        api = _api(None, secrets={"RECENT_LABS_NOTE_TYPE_ID": "nt-1"})
        with patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "Invalid JSON" in str(result[0])

    def test_no_values_returns_error(self):
        api = _api({"patient_id": "p1"}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "nt-1"})
        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[]), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "No lab results" in str(result[0])

    def test_unresolvable_note_type_returns_error(self):
        api = _api({"patient_id": "p1"}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "faxedlabs"})
        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[{"test_name": "A1c", "results": [{}]}]), \
             patch("recent_labs.protocols.fax_summary_api.resolve_note_type_id",
                   return_value=None), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "faxedlabs" in str(result[0])
        assert "not found" in str(result[0])

    def test_missing_logged_in_provider_returns_error(self):
        api = _api({"patient_id": "p1"}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "faxedlabs"},
                   headers={})  # no canvas-logged-in-user-id
        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[{"test_name": "A1c", "results": [{}]}]), \
             patch("recent_labs.protocols.fax_summary_api.resolve_note_type_id",
                   return_value="nt-uuid"), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "provider" in str(result[0]).lower()

    def test_no_practice_location_returns_error(self):
        api = _api({"patient_id": "p1"}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "faxedlabs"})
        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[{"test_name": "A1c", "results": [{}]}]), \
             patch("recent_labs.protocols.fax_summary_api.resolve_note_type_id",
                   return_value="nt-uuid"), \
             patch("recent_labs.protocols.fax_summary_api.first_active_practice_location_id",
                   return_value=None), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "practice location" in str(result[0]).lower()

    def test_creates_note_and_hpi_effects(self):
        api = _api({"patient_id": "p1"}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "faxedlabs"})

        note_effect = MagicMock(name="note_effect")
        command_effect = MagicMock(name="command_effect")
        note_instance = MagicMock()
        note_instance.create.return_value = note_effect
        command_instance = MagicMock()
        command_instance.originate.return_value = command_effect

        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[{"test_name": "A1c", "results": [{}]}]), \
             patch("recent_labs.protocols.fax_summary_api.resolve_note_type_id",
                   return_value="nt-uuid") as mock_resolve, \
             patch("recent_labs.protocols.fax_summary_api.first_active_practice_location_id",
                   return_value="loc-1"), \
             patch("recent_labs.protocols.fax_summary_api.build_fax_note_html",
                   return_value="<div>HTML</div>"), \
             patch("recent_labs.protocols.fax_summary_api.Note",
                   return_value=note_instance) as mock_note, \
             patch("recent_labs.protocols.fax_summary_api.CustomCommand",
                   return_value=command_instance) as mock_cmd, \
             patch("recent_labs.protocols.fax_summary_api.uuid4",
                   return_value="fixed-uuid"), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)

        mock_resolve.assert_called_once_with("faxedlabs")
        _, note_kwargs = mock_note.call_args
        assert note_kwargs["note_type_id"] == "nt-uuid"
        assert note_kwargs["patient_id"] == "p1"
        assert note_kwargs["provider_id"] == "staff-1"
        assert note_kwargs["practice_location_id"] == "loc-1"
        assert note_kwargs["instance_id"] == "fixed-uuid"
        assert "datetime_of_service" in note_kwargs

        _, cmd_kwargs = mock_cmd.call_args
        assert cmd_kwargs["note_uuid"] == "fixed-uuid"
        assert cmd_kwargs["schema_key"] == RECENT_LABS_SCHEMA_KEY
        assert cmd_kwargs["content"] == "<div>HTML</div>"
        assert cmd_kwargs["print_content"] == "<div>HTML</div>"

        assert note_effect in result
        assert command_effect in result
        assert any("success" in str(r) for r in result)

    def _patched_post(self, note_create_side_effect):
        """Run post() with everything stubbed so Note(...).create() raises the given error."""
        api = _api({"patient_id": "p1"}, secrets={"RECENT_LABS_NOTE_TYPE_ID": "faxedlabs"})
        note_instance = MagicMock()
        note_instance.create.side_effect = note_create_side_effect
        return api, note_instance

    def test_validation_error_returns_friendly_error(self):
        api, note_instance = self._patched_post(
            ValidationError.from_exception_data("Note", [])
        )
        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[{"test_name": "A1c", "results": [{}]}]), \
             patch("recent_labs.protocols.fax_summary_api.resolve_note_type_id",
                   return_value="nt-uuid"), \
             patch("recent_labs.protocols.fax_summary_api.first_active_practice_location_id",
                   return_value="loc-1"), \
             patch("recent_labs.protocols.fax_summary_api.build_fax_note_html",
                   return_value="<div>HTML</div>"), \
             patch("recent_labs.protocols.fax_summary_api.Note", return_value=note_instance), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            result = CreateFaxSummaryAPI.post(api)
        assert len(result) == 1
        assert "Could not create summary note" in str(result[0])

    def test_unexpected_error_propagates(self):
        api, note_instance = self._patched_post(RuntimeError("unexpected bug"))
        with patch("recent_labs.protocols.fax_summary_api.get_recent_results_by_test",
                   return_value=[{"test_name": "A1c", "results": [{}]}]), \
             patch("recent_labs.protocols.fax_summary_api.resolve_note_type_id",
                   return_value="nt-uuid"), \
             patch("recent_labs.protocols.fax_summary_api.first_active_practice_location_id",
                   return_value="loc-1"), \
             patch("recent_labs.protocols.fax_summary_api.build_fax_note_html",
                   return_value="<div>HTML</div>"), \
             patch("recent_labs.protocols.fax_summary_api.Note", return_value=note_instance), \
             patch("recent_labs.protocols.fax_summary_api.log"):
            with pytest.raises(RuntimeError, match="unexpected bug"):
                CreateFaxSummaryAPI.post(api)


class TestResolveNoteTypeId:
    def test_returns_uuid_when_valid_and_exists(self):
        u = "12345678-1234-5678-1234-567812345678"
        with patch("recent_labs.protocols.fax_summary_api.NoteType") as NT:
            NT.objects.filter.return_value.exists.return_value = True
            assert resolve_note_type_id(u) == u
        NT.objects.filter.assert_called_once_with(id=u)

    def test_resolves_by_code(self):
        with patch("recent_labs.protocols.fax_summary_api.NoteType") as NT:
            NT.objects.filter.return_value.values_list.return_value.first.return_value = "code-id"
            assert resolve_note_type_id("faxedlabs") == "code-id"
        # code is tried first
        NT.objects.filter.assert_called_once_with(is_active=True, code="faxedlabs")

    def test_falls_back_to_name_when_code_misses(self):
        with patch("recent_labs.protocols.fax_summary_api.NoteType") as NT:
            NT.objects.filter.return_value.values_list.return_value.first.side_effect = [None, "name-id"]
            assert resolve_note_type_id("Faxed Labs") == "name-id"
        assert NT.objects.filter.call_args_list == [
            call(is_active=True, code="Faxed Labs"),
            call(is_active=True, name="Faxed Labs"),
        ]

    def test_returns_none_when_nothing_matches(self):
        with patch("recent_labs.protocols.fax_summary_api.NoteType") as NT:
            NT.objects.filter.return_value.values_list.return_value.first.side_effect = [None, None]
            assert resolve_note_type_id("nope") is None


class TestFirstActivePracticeLocationId:
    def test_returns_id_when_present(self):
        with patch("recent_labs.protocols.fax_summary_api.PracticeLocation") as PL:
            PL.objects.filter.return_value.values_list.return_value.first.return_value = "loc-9"
            assert first_active_practice_location_id() == "loc-9"
        PL.objects.filter.assert_called_once_with(active=True)

    def test_returns_none_when_no_active_location(self):
        with patch("recent_labs.protocols.fax_summary_api.PracticeLocation") as PL:
            PL.objects.filter.return_value.values_list.return_value.first.return_value = None
            assert first_active_practice_location_id() is None


class TestBuildFaxNoteHtml:
    def test_renders_with_patient_name_and_dob(self):
        from datetime import date
        patient = SimpleNamespace(first_name="Jane", last_name="Doe", birth_date=date(1980, 1, 15))
        groups = [{"test_name": "A1c", "results": []}]
        with patch("recent_labs.protocols.fax_summary_api.Patient") as P, \
             patch("recent_labs.protocols.fax_summary_api.render_to_string",
                   return_value="<div>ok</div>") as mock_render:
            P.objects.filter.return_value.first.return_value = patient
            html = build_fax_note_html("p1", groups)
        assert html == "<div>ok</div>"
        template, ctx = mock_render.call_args.args
        assert template == "templates/fax_summary.html"
        assert ctx["patient_name"] == "Jane Doe"
        assert ctx["patient_dob"] == "01/15/1980"
        assert ctx["groups"] == groups

    def test_blank_patient_fields_when_patient_missing(self):
        with patch("recent_labs.protocols.fax_summary_api.Patient") as P, \
             patch("recent_labs.protocols.fax_summary_api.render_to_string",
                   return_value="<div></div>") as mock_render:
            P.objects.filter.return_value.first.return_value = None
            build_fax_note_html("p1", [])
        _, ctx = mock_render.call_args.args
        assert ctx["patient_name"] == ""
        assert ctx["patient_dob"] == ""
