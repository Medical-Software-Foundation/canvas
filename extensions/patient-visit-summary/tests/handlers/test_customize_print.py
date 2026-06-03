import base64
import json
from datetime import date, datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest
from requests import RequestException

from patient_visit_summary.handlers.customize_print import (
    CustomizePrintAPI,
    CustomizePrintButton,
    _compute_age,
    build_customize_print_context,
)

_CP = "patient_visit_summary.handlers.customize_print"


# --- CustomizePrintButton ---


class TestCustomizePrintButton:
    def test_button_title(self):
        assert CustomizePrintButton.BUTTON_TITLE == "Customize & Print"

    def test_button_key(self):
        assert CustomizePrintButton.BUTTON_KEY == "CUSTOMIZE_PRINT"

    def test_button_location(self):
        assert (
            CustomizePrintButton.BUTTON_LOCATION
            == CustomizePrintButton.ButtonLocation.NOTE_FOOTER
        )

    def test_visible_returns_true(self):
        handler = CustomizePrintButton.__new__(CustomizePrintButton)
        assert handler.visible() is True

    @patch(f"{_CP}.LaunchModalEffect")
    @patch(f"{_CP}.Note")
    @patch(f"{_CP}.log")
    def test_handle_resolves_note_uuid_into_url(self, mock_log, mock_note_cls, mock_modal):
        note = MagicMock()
        note.id = "note-uuid-xyz"
        mock_note_cls.objects.filter.return_value.first.return_value = note
        handler = CustomizePrintButton.__new__(CustomizePrintButton)
        mock_event = MagicMock()
        mock_event.context = {"note_id": "456"}
        handler.event = mock_event
        handler._target = "patient-123"

        with patch.object(
            type(handler),
            "target",
            new_callable=lambda: property(lambda self: self._target),
        ):
            effects = handler.handle()

        assert len(effects) == 1
        # dbid from the event context is resolved to the external UUID, and
        # only the UUID ends up in the (browser-visible) modal URL.
        mock_note_cls.objects.filter.assert_called_once_with(dbid="456")
        url = mock_modal.call_args.kwargs["url"]
        assert "note_id=note-uuid-xyz" in url
        assert "patient_id=patient-123" in url
        assert "&v=" in url  # cache-busting token on the modal URL
        assert mock_log.info.called

    @patch(f"{_CP}.LaunchModalEffect")
    @patch(f"{_CP}.Note")
    @patch(f"{_CP}.log")
    def test_handle_missing_note_yields_empty_note_id(self, mock_log, mock_note_cls, mock_modal):
        mock_note_cls.objects.filter.return_value.first.return_value = None
        handler = CustomizePrintButton.__new__(CustomizePrintButton)
        mock_event = MagicMock()
        mock_event.context = {"note_id": "456"}
        handler.event = mock_event
        handler._target = "patient-123"

        with patch.object(
            type(handler),
            "target",
            new_callable=lambda: property(lambda self: self._target),
        ):
            effects = handler.handle()

        assert len(effects) == 1
        url = mock_modal.call_args.kwargs["url"]
        assert "note_id=" in url and "note_id=note-uuid" not in url


# --- _compute_age ---


class TestComputeAge:
    def test_no_birth_date(self):
        assert _compute_age(None) == ""

    def test_birthday_passed_this_year(self):
        bd = date(date.today().year - 30, 1, 1)
        assert _compute_age(bd) == "30"

    def test_birthday_not_yet_this_year(self):
        # A birthday in December for someone "born" last year should not yet count.
        today = date.today()
        bd = date(today.year - 5, 12, 31)
        expected = 5 if (today.month, today.day) >= (12, 31) else 4
        assert _compute_age(bd) == str(expected)

    def test_future_birth_date_returns_empty(self):
        bd = date(date.today().year + 1, 1, 1)
        assert _compute_age(bd) == ""


# --- build_customize_print_context ---


def _patient(birth_date=date(1985, 3, 15), sex="F"):
    p = MagicMock()
    p.first_name = "Jane"
    p.last_name = "Doe"
    p.birth_date = birth_date
    p.sex_at_birth = sex
    return p


def _provider():
    pr = MagicMock()
    pr.first_name = "John"
    pr.last_name = "Smith"
    return pr


class TestBuildCustomizePrintContext:
    @patch(f"{_CP}.render_blocks")
    @patch(f"{_CP}.enumerate_sections")
    def test_single_entry_group(self, mock_enum, mock_render):
        mock_enum.return_value = [
            {
                "key": "hpi",
                "title": "HPI",
                "groups": [
                    {
                        "display_name": "HPI",
                        "entries": [{"title": "HPI", "blocks": [{"kind": "text"}]}],
                    }
                ],
            }
        ]
        mock_render.return_value = "<p>rendered</p>"
        role = MagicMock()
        role.public_abbreviation = "MD"
        note = MagicMock()
        note.dbid = 99
        note.id = "note-uuid-abc"

        ctx = {
            "patient": _patient(),
            "provider": _provider(),
            "provider_top_role": role,
            "appointment_date": "January 15, 2025",
            "note": note,
        }

        result = build_customize_print_context(ctx)

        assert result["appointment_date"] == "January 15, 2025"
        assert result["note_dbid"] == 99
        # The JS uses note_uuid as the note_id sent to the API (resolved by Note.id).
        assert result["note_uuid"] == "note-uuid-abc"
        assert len(result["sections"]) == 1
        assert result["sections"][0]["items"][0]["display"] == "HPI"
        note_data = json.loads(result["note_data_json"])
        assert note_data["header"]["providerName"] == "John Smith, MD"
        assert note_data["commands"][0]["printHtml"] == "<p>rendered</p>"
        mock_render.assert_called_once_with([{"kind": "text"}])

    @patch(f"{_CP}.render_blocks")
    @patch(f"{_CP}.enumerate_sections")
    def test_multi_entry_group_creates_children(self, mock_enum, mock_render):
        mock_enum.return_value = [
            {
                "key": "plan",
                "title": "Plan",
                "groups": [
                    {
                        "display_name": "Plan",
                        "entries": [
                            {"title": "A", "blocks": [{"kind": "a"}]},
                            {"title": "B", "blocks": [{"kind": "b"}]},
                        ],
                    }
                ],
            }
        ]
        mock_render.return_value = "<p>x</p>"
        ctx = {
            "patient": _patient(birth_date=None, sex=None),
            "provider": _provider(),
            "provider_top_role": None,
            "note": None,
        }

        result = build_customize_print_context(ctx)

        items = result["sections"][0]["items"]
        assert items[0]["display"] == "Plan (2)"
        assert len(items[0]["children"]) == 2
        assert result["note_dbid"] == ""
        # birth_date None -> dob empty, age empty, sex empty
        note_data = json.loads(result["note_data_json"])
        assert note_data["header"]["dob"] == ""
        assert note_data["header"]["sex"] == ""
        assert note_data["header"]["providerName"] == "John Smith"
        assert mock_render.call_count == 2

    @patch(f"{_CP}.render_blocks")
    @patch(f"{_CP}.enumerate_sections")
    def test_single_follow_up_appends_to_existing_plan(self, mock_enum, mock_render):
        mock_enum.return_value = [
            {
                "key": "plan",
                "title": "Plan",
                "groups": [
                    {
                        "display_name": "Plan",
                        "entries": [{"title": "Plan", "blocks": [{"kind": "p"}]}],
                    }
                ],
            }
        ]
        mock_render.return_value = "<p>fu</p>"
        ctx = {
            "patient": _patient(),
            "provider": _provider(),
            "provider_top_role": None,
            "note": None,
            "follow_ups": [
                {
                    "date": "2025-06-15",
                    "rfv": "Recheck",
                    "note_type": "Office Visit",
                    "comment": "bring labs",
                }
            ],
        }

        result = build_customize_print_context(ctx)

        plan_section = next(s for s in result["sections"] if s["key"] == "plan")
        displays = [item["display"] for item in plan_section["items"]]
        assert "Follow Up" in displays
        note_data = json.loads(result["note_data_json"])
        fu_cmds = [c for c in note_data["commands"] if c["displayText"] == "Follow Up"]
        assert len(fu_cmds) == 1

    @patch(f"{_CP}.render_blocks")
    @patch(f"{_CP}.enumerate_sections")
    def test_multiple_follow_ups_create_plan_section_and_children(
        self, mock_enum, mock_render
    ):
        # No plan section emitted by enumerate_sections -> code must synthesize one.
        mock_enum.return_value = []
        mock_render.return_value = "<p>fu</p>"
        ctx = {
            "patient": _patient(),
            "provider": _provider(),
            "provider_top_role": None,
            "note": None,
            "follow_ups": [
                {"date": "2025-06-15", "rfv": "Recheck", "note_type": "Office Visit"},
                {"date": "", "rfv": "Second", "note_type": ""},
            ],
        }

        result = build_customize_print_context(ctx)

        plan_section = next(s for s in result["sections"] if s["key"] == "plan")
        assert plan_section["items"][0]["display"] == "Follow Up (2)"
        assert len(plan_section["items"][0]["children"]) == 2
        assert mock_render.call_count == 2

    @patch(f"{_CP}.render_blocks")
    @patch(f"{_CP}.enumerate_sections")
    def test_follow_up_fallback_singular_fields(self, mock_enum, mock_render):
        mock_enum.return_value = []
        mock_render.return_value = "<p>fu</p>"
        ctx = {
            "patient": _patient(),
            "provider": _provider(),
            "provider_top_role": None,
            "note": None,
            "follow_up_date": "2025-07-01",
            "follow_up_rfv": "Check",
            "follow_up_note_type": "Telehealth",
        }

        result = build_customize_print_context(ctx)

        plan_section = next(s for s in result["sections"] if s["key"] == "plan")
        assert plan_section["items"][0]["display"] == "Follow Up"
        mock_render.assert_called_once()

    @patch(f"{_CP}.render_blocks")
    @patch(f"{_CP}.enumerate_sections")
    def test_no_follow_ups(self, mock_enum, mock_render):
        mock_enum.return_value = []
        ctx = {
            "patient": _patient(),
            "provider": _provider(),
            "provider_top_role": None,
            "note": None,
        }

        result = build_customize_print_context(ctx)

        assert result["sections"] == []
        mock_render.assert_not_called()


# --- CustomizePrintAPI.authenticate ---


class TestAuthenticate:
    def _make_handler(self, request, secrets):
        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = request
        handler.secrets = secrets
        return handler

    @patch(f"{_CP}.SessionCredentials")
    def test_staff_session_authenticates(self, mock_session_cls, mock_request, mock_secrets):
        mock_session_cls.return_value.logged_in_user = {"type": "Staff"}
        handler = self._make_handler(mock_request, mock_secrets)

        assert handler.authenticate(MagicMock()) is True
        assert mock_session_cls.mock_calls == [call(mock_request)]

    @patch(f"{_CP}.SessionCredentials")
    def test_non_staff_falls_to_api_key(self, mock_session_cls, mock_request, mock_secrets):
        mock_session_cls.return_value.logged_in_user = {"type": "Patient"}
        mock_request.headers = {"Authorization": "test-secret-key-123"}
        handler = self._make_handler(mock_request, mock_secrets)

        assert handler.authenticate(MagicMock()) is True

    @patch(f"{_CP}.SessionCredentials")
    def test_invalid_session_falls_to_api_key(self, mock_session_cls, mock_request, mock_secrets):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {"Authorization": "test-secret-key-123"}
        handler = self._make_handler(mock_request, mock_secrets)

        assert handler.authenticate(MagicMock()) is True

    @patch(f"{_CP}.SessionCredentials")
    def test_wrong_api_key_rejected(self, mock_session_cls, mock_request, mock_secrets):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {"Authorization": "wrong"}
        handler = self._make_handler(mock_request, mock_secrets)

        assert handler.authenticate(MagicMock()) is False

    @patch(f"{_CP}.SessionCredentials")
    def test_missing_secret_rejected(self, mock_session_cls, mock_request):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {"Authorization": "any"}
        handler = self._make_handler(mock_request, {})

        assert handler.authenticate(MagicMock()) is False

    @patch(f"{_CP}.SessionCredentials")
    def test_missing_auth_header_rejected(self, mock_session_cls, mock_request, mock_secrets):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        mock_session_cls.side_effect = InvalidCredentialsError
        mock_request.headers = {}
        handler = self._make_handler(mock_request, mock_secrets)

        assert handler.authenticate(MagicMock()) is False


# --- _get_or_create_preference ---


class TestGetOrCreatePreference:
    def _handler(self):
        return CustomizePrintAPI.__new__(CustomizePrintAPI)

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch(f"{_CP}.Note")
    def test_note_not_found_returns_none(self, mock_note_cls, mock_cnp):
        mock_note_cls.objects.filter.return_value.first.return_value = None
        handler = self._handler()

        assert handler._get_or_create_preference("5") is None
        mock_note_cls.objects.filter.assert_called_once_with(id="5")
        mock_cnp.objects.create.assert_not_called()

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch(f"{_CP}.Note")
    def test_existing_draft_returned(self, mock_note_cls, mock_cnp):
        note = MagicMock()
        mock_note_cls.objects.filter.return_value.first.return_value = note
        existing = MagicMock()
        mock_cnp.objects.filter.return_value.order_by.return_value.first.return_value = existing
        handler = self._handler()

        result = handler._get_or_create_preference("5")

        assert result is existing
        mock_cnp.objects.create.assert_not_called()

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch(f"{_CP}.Note")
    def test_creates_new_draft_when_none(self, mock_note_cls, mock_cnp):
        note = MagicMock()
        mock_note_cls.objects.filter.return_value.first.return_value = note
        mock_cnp.objects.filter.return_value.order_by.return_value.first.return_value = None
        created = MagicMock()
        mock_cnp.objects.create.return_value = created
        mock_cnp.STATUS_DRAFT = "draft"
        handler = self._handler()

        result = handler._get_or_create_preference("5")

        assert result is created
        mock_cnp.objects.create.assert_called_once_with(note=note, status="draft")


# --- index ---


class TestIndex:
    @patch(f"{_CP}.render_to_string")
    @patch(f"{_CP}.build_customize_print_context")
    @patch(f"{_CP}.NoteDataExtractor")
    def test_returns_html(self, mock_nde, mock_build, mock_render, mock_request):
        mock_request.query_params = {"patient_id": "p1", "note_id": "n1"}
        extractor = MagicMock()
        extractor.get_template_context.return_value = {"x": 1}
        mock_nde.return_value = extractor
        mock_build.return_value = {"ctx": True}
        mock_render.return_value = "<html></html>"

        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = mock_request

        result = handler.index()

        assert len(result) == 1
        assert result[0].status_code == HTTPStatus.OK
        mock_nde.assert_called_once_with(patient_id="p1", note_id="n1")
        mock_build.assert_called_once_with({"x": 1})
        # cache_bust is injected into the render context for browser cache busting.
        render_args, render_kwargs = mock_render.call_args
        assert render_args[0] == "templates/customize_print.html"
        assert render_kwargs["context"]["ctx"] is True
        assert render_kwargs["context"]["cache_bust"]


# --- get_state ---


class TestGetState:
    def _handler(self, query_params):
        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = MagicMock()
        handler.request.query_params = query_params
        return handler

    def test_missing_note_id(self):
        handler = self._handler({})
        result = handler.get_state()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch.object(CustomizePrintAPI, "_get_or_create_preference", return_value=None)
    def test_note_not_found(self, mock_pref):
        handler = self._handler({"note_id": "5"})
        result = handler.get_state()
        assert result[0].status_code == HTTPStatus.NOT_FOUND
        mock_pref.assert_called_once_with("5")

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    def test_returns_state(self, mock_pref, mock_cnp):
        pref = MagicMock()
        pref.header_text = "H"
        pref.footer_text = "F"
        pref.selection = {"a": 1}
        pref.status = "draft"
        pref.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_pref.return_value = pref
        handler = self._handler({"note_id": "5"})

        result = handler.get_state()

        assert result[0].status_code == HTTPStatus.OK
        mock_pref.assert_called_once_with("5")

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    def test_returns_state_with_defaults(self, mock_pref, mock_cnp):
        mock_cnp.STATUS_DRAFT = "draft"
        pref = MagicMock()
        pref.header_text = ""
        pref.footer_text = ""
        pref.selection = None
        pref.status = None
        pref.updated_at = None
        mock_pref.return_value = pref
        handler = self._handler({"note_id": "5"})

        result = handler.get_state()

        assert result[0].status_code == HTTPStatus.OK


# --- save_state ---


class TestSaveState:
    def _handler(self):
        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = MagicMock()
        return handler

    def test_invalid_json(self):
        handler = self._handler()
        handler.request.json.side_effect = ValueError("bad")
        result = handler.save_state()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_note_id(self):
        handler = self._handler()
        handler.request.json.return_value = {"header_text": "x"}
        result = handler.save_state()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_non_dict_body(self):
        handler = self._handler()
        handler.request.json.return_value = ["not", "a", "dict"]
        result = handler.save_state()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch.object(CustomizePrintAPI, "_get_or_create_preference", return_value=None)
    def test_note_not_found(self, mock_pref):
        handler = self._handler()
        handler.request.json.return_value = {"note_id": "5"}
        result = handler.save_state()
        assert result[0].status_code == HTTPStatus.NOT_FOUND
        mock_pref.assert_called_once_with("5")

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    def test_saves_all_fields_with_final_status(self, mock_pref, mock_cnp):
        mock_cnp.STATUS_DRAFT = "draft"
        mock_cnp.STATUS_FINAL = "final"
        pref = MagicMock()
        pref.status = "final"
        pref.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_pref.return_value = pref
        handler = self._handler()
        handler.request.json.return_value = {
            "note_id": "5",
            "header_text": "Header",
            "footer_text": "Footer",
            "selection": {"x": 1},
            "status": "final",
        }

        result = handler.save_state()

        assert pref.header_text == "Header"
        assert pref.footer_text == "Footer"
        assert pref.selection == {"x": 1}
        assert pref.status == "final"
        pref.save.assert_called_once()
        assert result[0].status_code == HTTPStatus.OK

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    def test_invalid_status_ignored_and_non_dict_selection(self, mock_pref, mock_cnp):
        mock_cnp.STATUS_DRAFT = "draft"
        mock_cnp.STATUS_FINAL = "final"
        pref = MagicMock()
        pref.status = "draft"
        pref.updated_at = None
        mock_pref.return_value = pref
        handler = self._handler()
        handler.request.json.return_value = {
            "note_id": "5",
            "selection": "not-a-dict",
            "status": "bogus",
        }

        result = handler.save_state()

        # selection should not have been set to the string
        assert pref.selection != "not-a-dict"
        pref.save.assert_called_once()
        assert result[0].status_code == HTTPStatus.OK


# --- list_finals ---


class TestListFinals:
    def _handler(self, note_id="5"):
        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = MagicMock()
        handler.request.query_params = {"note_id": note_id} if note_id else {}
        return handler

    def test_missing_note_id(self):
        handler = self._handler(note_id=None)
        result = handler.list_finals()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch(f"{_CP}.Note")
    def test_note_not_found(self, mock_note_cls):
        mock_note_cls.objects.filter.return_value.first.return_value = None
        handler = self._handler()
        result = handler.list_finals()
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch(f"{_CP}.Note")
    def test_with_doc_ref(self, mock_note_cls, mock_cnp):
        note = MagicMock()
        mock_note_cls.objects.filter.return_value.first.return_value = note
        mock_cnp.STATUS_FINAL = "final"

        doc_ref = MagicMock()
        doc_ref.id = "doc-1"
        row = MagicMock()
        row.uuid = "11111111-2222-3333-4444-555555555555"
        row.document_reference = doc_ref
        row.description = "My Print"
        row.pdf_generated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        qs = (
            mock_cnp.objects.filter.return_value.order_by.return_value
            .select_related.return_value.defer.return_value
        )
        qs.__iter__ = MagicMock(return_value=iter([row]))

        handler = self._handler()
        result = handler.list_finals()

        assert result[0].status_code == HTTPStatus.OK
        body = json.loads(result[0].content)
        assert body["finals"][0]["id"] == "11111111-2222-3333-4444-555555555555"
        assert body["finals"][0]["pdf_url"].endswith(
            "/finals/11111111-2222-3333-4444-555555555555/pdf"
        )
        assert body["finals"][0]["document_reference_id"] == "doc-1"
        assert body["finals"][0]["description"] == "My Print"

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch(f"{_CP}.Note")
    def test_doc_ref_description_fallback(self, mock_note_cls, mock_cnp):
        note = MagicMock()
        mock_note_cls.objects.filter.return_value.first.return_value = note
        mock_cnp.STATUS_FINAL = "final"

        doc_ref = MagicMock()
        doc_ref.id = "doc-2"
        doc_ref.related_object_document_title = "Fallback Title"
        row = MagicMock()
        row.dbid = 7
        row.document_reference = doc_ref
        row.description = ""
        row.pdf_generated_at = None

        qs = (
            mock_cnp.objects.filter.return_value.order_by.return_value
            .select_related.return_value.defer.return_value
        )
        qs.__iter__ = MagicMock(return_value=iter([row]))

        handler = self._handler()
        result = handler.list_finals()

        body = json.loads(result[0].content)
        assert body["finals"][0]["description"] == "Fallback Title"
        assert body["finals"][0]["generated_at"] is None

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch(f"{_CP}.Note")
    def test_no_doc_ref(self, mock_note_cls, mock_cnp):
        note = MagicMock()
        mock_note_cls.objects.filter.return_value.first.return_value = note
        mock_cnp.STATUS_FINAL = "final"

        row = MagicMock()
        row.dbid = 8
        row.document_reference = None
        row.description = "Desc"
        row.pdf_generated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        qs = (
            mock_cnp.objects.filter.return_value.order_by.return_value
            .select_related.return_value.defer.return_value
        )
        qs.__iter__ = MagicMock(return_value=iter([row]))

        handler = self._handler()
        result = handler.list_finals()

        body = json.loads(result[0].content)
        assert body["finals"][0]["document_reference_id"] == ""


# --- serve_final_pdf ---


_VALID_UUID = "12345678-1234-5678-1234-567812345678"


class TestServeFinalPdf:
    def _handler(self, final_uuid):
        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = MagicMock()
        handler.request.path_params = {"final_uuid": final_uuid} if final_uuid is not None else {}
        return handler

    def test_missing_final_uuid(self):
        handler = self._handler(None)
        result = handler.serve_final_pdf()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_uuid(self):
        handler = self._handler("not-a-uuid")
        result = handler.serve_final_pdf()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch(f"{_CP}.CustomizedNotePrint")
    def test_row_not_found(self, mock_cnp):
        mock_cnp.objects.filter.return_value.only.return_value.first.return_value = None
        handler = self._handler(_VALID_UUID)
        result = handler.serve_final_pdf()
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    @patch(f"{_CP}.CustomizedNotePrint")
    def test_row_without_base64(self, mock_cnp):
        row = MagicMock()
        row.pdf_base64 = ""
        mock_cnp.objects.filter.return_value.only.return_value.first.return_value = row
        handler = self._handler(_VALID_UUID)
        result = handler.serve_final_pdf()
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    @patch(f"{_CP}.CustomizedNotePrint")
    def test_bad_base64(self, mock_cnp):
        row = MagicMock()
        row.pdf_base64 = "!!!not-valid-base64!!!"
        mock_cnp.objects.filter.return_value.only.return_value.first.return_value = row
        handler = self._handler(_VALID_UUID)
        with patch(f"{_CP}.base64.b64decode", side_effect=ValueError("bad")):
            result = handler.serve_final_pdf()
        assert result[0].status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @patch(f"{_CP}.CustomizedNotePrint")
    def test_serves_pdf(self, mock_cnp):
        row = MagicMock()
        row.pdf_base64 = base64.b64encode(b"PDFDATA").decode("ascii")
        mock_cnp.objects.filter.return_value.only.return_value.first.return_value = row
        handler = self._handler(_VALID_UUID)
        result = handler.serve_final_pdf()
        assert result[0].status_code == HTTPStatus.OK
        mock_cnp.objects.filter.assert_called_once_with(uuid=str(UUID(_VALID_UUID)))


# --- print_pdf ---


class TestPrintPdf:
    def _handler(self, secrets=None):
        handler = CustomizePrintAPI.__new__(CustomizePrintAPI)
        handler.request = MagicMock()
        handler.secrets = secrets if secrets is not None else {}
        return handler

    def test_invalid_json(self):
        handler = self._handler()
        handler.request.json.side_effect = ValueError("bad")
        result = handler.print_pdf()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_missing_note_id_or_html(self):
        handler = self._handler()
        handler.request.json.return_value = {"note_id": "5"}
        result = handler.print_pdf()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    @patch(f"{_CP}.Note")
    def test_note_not_found(self, mock_note_cls):
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = None
        handler = self._handler()
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}
        result = handler.print_pdf()
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    @patch(f"{_CP}.Note")
    def test_no_patient_on_note(self, mock_note_cls):
        note = MagicMock()
        note.patient = None
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        handler = self._handler()
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}
        result = handler.print_pdf()
        assert result[0].status_code == HTTPStatus.NOT_FOUND

    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_pdf_generation_failed(self, mock_note_cls, mock_pdf_gen):
        note = MagicMock()
        note.patient.id = "pat-1"
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value = None
        handler = self._handler()
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.BAD_GATEWAY
        mock_pdf_gen.from_html.assert_called_once_with("<p>x</p>")

    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_pdf_download_failed(self, mock_note_cls, mock_pdf_gen, mock_http):
        note = MagicMock()
        note.patient.id = "pat-1"
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        mock_http.return_value.get.side_effect = RequestException("network down")
        handler = self._handler()
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.BAD_GATEWAY
        mock_http.return_value.get.assert_called_once_with("https://pdf")

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_skipped_no_credentials(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref, mock_cnp
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp
        pref = MagicMock()
        mock_pref.return_value = pref
        handler = self._handler(secrets={})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK
        body = json.loads(result[0].content)
        assert body["document_reference_id"] == ""
        # pref saved as final
        assert pref.status == "final"
        pref.save.assert_called_once()

    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_skipped_no_reviewer(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref, mock_cnp
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider = None
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp
        mock_pref.return_value = None
        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK

    @patch(f"{_CP}.DocumentReference")
    @patch(f"{_CP}.CanvasFhir")
    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_create_success(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref,
        mock_cnp, mock_fhir_cls, mock_docref_cls,
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        note.datetime_of_service = datetime(2025, 1, 15, tzinfo=timezone.utc)
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp

        fhir = MagicMock()
        fhir.create.return_value = {"id": "fhir-doc-1"}
        mock_fhir_cls.return_value = fhir

        recent_doc = MagicMock()
        recent_doc.id = "fhir-doc-1"
        recent_doc.dbid = 100
        mock_docref_cls.objects.for_patient.return_value.filter.return_value.order_by.return_value.first.return_value = recent_doc

        pref = MagicMock()
        mock_pref.return_value = pref

        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {
            "note_id": "5", "html": "<p>x</p>", "description": "Visit Doc",
        }

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK
        body = json.loads(result[0].content)
        assert body["document_reference_id"] == "fhir-doc-1"
        mock_fhir_cls.assert_called_once_with(client_id="id", client_secret="sec")
        assert fhir.create.call_args[0][0] == "DocumentReference"
        assert pref.document_reference is recent_doc
        assert pref.description == "Visit Doc"
        pref.save.assert_called_once()

    @patch(f"{_CP}.DocumentReference")
    @patch(f"{_CP}.CanvasFhir")
    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_create_raises_json_decode_then_lookup_by_id(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref,
        mock_cnp, mock_fhir_cls, mock_docref_cls,
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        note.datetime_of_service = None
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp

        fhir = MagicMock()
        fhir.create.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_fhir_cls.return_value = fhir

        # No recent by created date, but doc_ref_fhir_id empty too -> falls to newest for patient.
        for_patient = mock_docref_cls.objects.for_patient.return_value
        for_patient.filter.return_value.order_by.return_value.first.return_value = None
        for_patient.order_by.return_value.first.return_value = None

        pref = MagicMock()
        mock_pref.return_value = pref

        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK
        # doc_ref never resolved
        body = json.loads(result[0].content)
        assert body["document_reference_id"] == ""

    @patch(f"{_CP}.DocumentReference")
    @patch(f"{_CP}.CanvasFhir")
    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_create_raises_http_error_with_response(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref,
        mock_cnp, mock_fhir_cls, mock_docref_cls,
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        note.datetime_of_service = datetime(2025, 1, 15, tzinfo=timezone.utc)
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp

        exc = RuntimeError("HTTP 500")
        http_resp = MagicMock()
        http_resp.text = "error body"
        exc.response = http_resp
        fhir = MagicMock()
        fhir.create.side_effect = exc
        mock_fhir_cls.return_value = fhir

        # Recent lookup by created date returns a doc.
        recent_doc = MagicMock()
        recent_doc.id = "doc-x"
        recent_doc.dbid = 55
        mock_docref_cls.objects.for_patient.return_value.filter.return_value.order_by.return_value.first.return_value = recent_doc

        pref = MagicMock()
        mock_pref.return_value = pref

        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK
        body = json.loads(result[0].content)
        assert body["document_reference_id"] == "doc-x"

    @patch(f"{_CP}.DocumentReference")
    @patch(f"{_CP}.CanvasFhir")
    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_unexpected_exc_and_lookup_by_fhir_id(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref,
        mock_cnp, mock_fhir_cls, mock_docref_cls,
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        note.datetime_of_service = datetime(2025, 1, 15, tzinfo=timezone.utc)
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp

        # create returns a dict with id, but then raise during the id parse? Instead:
        # Make create succeed returning id, but recent-by-date None so it looks up by fhir id.
        fhir = MagicMock()
        fhir.create.return_value = {"id": "from-resp"}
        mock_fhir_cls.return_value = fhir

        for_patient = mock_docref_cls.objects.for_patient.return_value
        for_patient.filter.return_value.order_by.return_value.first.return_value = None
        by_id_doc = MagicMock()
        by_id_doc.id = "from-resp"
        by_id_doc.dbid = 77
        mock_docref_cls.objects.filter.return_value.first.return_value = by_id_doc

        pref = MagicMock()
        mock_pref.return_value = pref

        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK
        body = json.loads(result[0].content)
        assert body["document_reference_id"] == "from-resp"
        mock_docref_cls.objects.filter.assert_called_once_with(id="from-resp")

    @patch(f"{_CP}.DocumentReference")
    @patch(f"{_CP}.CanvasFhir")
    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_error_response_text_raises(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref,
        mock_cnp, mock_fhir_cls, mock_docref_cls,
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        note.datetime_of_service = datetime(2025, 1, 15, tzinfo=timezone.utc)
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp

        # Exception with a response object whose .text access raises.
        exc = RuntimeError("HTTP 500")
        http_resp = MagicMock()
        type(http_resp).text = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("text boom"))
        )
        exc.response = http_resp
        fhir = MagicMock()
        fhir.create.side_effect = exc
        mock_fhir_cls.return_value = fhir

        mock_docref_cls.objects.for_patient.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_docref_cls.objects.for_patient.return_value.order_by.return_value.first.return_value = None

        pref = MagicMock()
        mock_pref.return_value = pref

        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log"):
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK

    @patch(f"{_CP}.DocumentReference")
    @patch(f"{_CP}.CanvasFhir")
    @patch(f"{_CP}.CustomizedNotePrint")
    @patch.object(CustomizePrintAPI, "_get_or_create_preference")
    @patch(f"{_CP}.Http")
    @patch(f"{_CP}.pdf_generator")
    @patch(f"{_CP}.Note")
    def test_fhir_create_raises_unexpected_no_response(
        self, mock_note_cls, mock_pdf_gen, mock_http, mock_pref,
        mock_cnp, mock_fhir_cls, mock_docref_cls,
    ):
        mock_cnp.STATUS_FINAL = "final"
        note = MagicMock()
        note.patient.id = "pat-1"
        note.provider.id = "prov-1"
        note.datetime_of_service = datetime(2025, 1, 15, tzinfo=timezone.utc)
        mock_note_cls.objects.filter.return_value.select_related.return_value.first.return_value = note
        mock_pdf_gen.from_html.return_value.url = "https://pdf"
        resp = MagicMock()
        resp.content = b"PDFBYTES"
        mock_http.return_value.get.return_value = resp

        # Plain exception: no .response attr, not a JSONDecodeError -> else branch.
        exc = ValueError("weird failure")
        exc.response = None
        fhir = MagicMock()
        fhir.create.side_effect = exc
        mock_fhir_cls.return_value = fhir

        mock_docref_cls.objects.for_patient.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_docref_cls.objects.for_patient.return_value.order_by.return_value.first.return_value = None

        pref = MagicMock()
        mock_pref.return_value = pref

        handler = self._handler(secrets={"fhir-client-id": "id", "fhir-client-secret": "sec"})
        handler.request.json.return_value = {"note_id": "5", "html": "<p>x</p>"}

        with patch(f"{_CP}.log") as mock_log:
            result = handler.print_pdf()

        assert result[0].status_code == HTTPStatus.OK
        assert mock_log.warning.called
