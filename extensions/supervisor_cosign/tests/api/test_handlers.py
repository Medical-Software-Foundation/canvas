"""Tests for supervisor_cosign.api.handlers."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest

from supervisor_cosign.api.handlers import SupervisorCoSignAPI


MODULE = "supervisor_cosign.api.handlers"


def _make_handler(json_body=None, path_params=None, query_params=None, user_id="sup-1"):
    handler = SupervisorCoSignAPI.__new__(SupervisorCoSignAPI)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler.request = MagicMock()
    handler.request.path_params = path_params or {}
    handler.request.query_params = query_params or {}
    handler.request.json.return_value = json_body or {}
    # The route handler reads canvas-logged-in-user-id from request.headers
    # (not from a self attribute set in authenticate, which runs in a different instance).
    handler.request.headers = {"canvas-logged-in-user-id": user_id}
    return handler


def _parse(response):
    body = json.loads(response.content) if isinstance(response.content, (bytes, str)) else response.content
    return body, response.status_code


class TestAuthenticate:
    # Authentication is provided by the SDK's StaffSessionAuthMixin: staff sessions
    # pass, non-staff raise InvalidCredentialsError, and SessionCredentials itself
    # rejects requests missing the Canvas-set user headers (so id presence is
    # guaranteed before authenticate() runs).
    def test_true_for_staff_session(self):
        handler = _make_handler()
        creds = MagicMock()
        creds.logged_in_user = {"type": "Staff", "id": "staff-1"}
        assert handler.authenticate(creds) is True

    def test_rejects_patient_session(self):
        from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError

        handler = _make_handler()
        creds = MagicMock()
        creds.logged_in_user = {"type": "Patient", "id": "pat-1"}
        with pytest.raises(InvalidCredentialsError):
            handler.authenticate(creds)


class TestLoggedInUserId:
    def test_reads_from_request_headers(self):
        handler = _make_handler(user_id="staff-99")
        assert handler._logged_in_user_id() == "staff-99"

    def test_returns_empty_when_header_missing(self):
        handler = _make_handler()
        handler.request.headers = {}
        assert handler._logged_in_user_id() == ""


class TestEscapeHtml:
    def test_escapes_special_chars(self):
        handler = _make_handler()
        assert handler._escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_passthrough_plain_text(self):
        handler = _make_handler()
        assert handler._escape_html("plain text") == "plain text"


class TestResolveAttestation:
    def test_custom_returns_custom_text(self):
        handler = _make_handler()
        assert handler._resolve_attestation("custom", "my words", "Sue") == "my words"

    def test_teaching_template_replaces_supervisee(self):
        handler = _make_handler()
        result = handler._resolve_attestation("teaching", "", "Sue Smith")
        assert "Sue Smith" in result
        assert "{{supervisee}}" not in result

    def test_reviewed_template_replaces_supervisee(self):
        handler = _make_handler()
        result = handler._resolve_attestation("reviewed", "", "Sue Smith")
        assert "Sue Smith" in result

    def test_personally_performed_no_placeholder(self):
        handler = _make_handler()
        result = handler._resolve_attestation("personally_performed", "", "Sue Smith")
        assert "personally performed" in result

    def test_unknown_template_returns_empty(self):
        handler = _make_handler()
        assert handler._resolve_attestation("not-a-template", "", "Sue") == ""

    def test_edited_text_wins_over_template(self):
        # If the supervisor picked a template and then edited the textarea,
        # the edited content must be used - not silently overwritten by the
        # canonical template text.
        handler = _make_handler()
        result = handler._resolve_attestation(
            "teaching",
            "I personally examined the patient and concur.",
            "Sue Smith",
        )
        assert result == "I personally examined the patient and concur."
        assert "critical and key portions" not in result

    def test_whitespace_only_text_falls_back_to_template(self):
        handler = _make_handler()
        result = handler._resolve_attestation("teaching", "   \n  ", "Sue")
        assert "Sue" in result
        assert "{{supervisee}}" not in result


class TestStaffName:
    def test_empty_id(self):
        assert _make_handler()._staff_name("") == ""

    def test_not_found(self):
        handler = _make_handler()
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values.return_value.first.return_value = None
            assert handler._staff_name("missing") == ""

    def test_found(self):
        handler = _make_handler()
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.values.return_value.first.return_value = {
                "first_name": "Sara",
                "last_name": "Sup",
            }
            assert handler._staff_name("staff-1") == "Sara Sup"


class TestStaffCredentialedName:
    def test_empty_id(self):
        assert _make_handler()._staff_credentialed_name("") == ""

    def test_staff_not_found(self):
        handler = _make_handler()
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = None
            assert handler._staff_credentialed_name("missing") == ""

    def test_returns_credentialed_name_when_present(self):
        handler = _make_handler()
        staff = MagicMock()
        staff.credentialed_name = "Sara Sup, MD"
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = staff
            assert handler._staff_credentialed_name("s-1") == "Sara Sup, MD"

    def test_falls_back_to_first_last_when_credentialed_blank(self):
        handler = _make_handler()
        staff = MagicMock()
        staff.credentialed_name = ""
        staff.first_name = "Sara"
        staff.last_name = "Sup"
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = staff
            assert handler._staff_credentialed_name("s-1") == "Sara Sup"

    def test_falls_back_when_credentialed_attribute_missing(self):
        # If the Staff model has no `credentialed_name` attribute at all,
        # getattr() returns None and we fall back to first+last. Real SDK
        # errors (not just attribute-missing) are intentionally allowed to
        # propagate to Sentry per REVIEW.md rule #3 - no blanket try/except.
        handler = _make_handler()
        staff = MagicMock(spec=["first_name", "last_name"])
        staff.first_name = "Sara"
        staff.last_name = "Sup"
        with patch(f"{MODULE}.Staff") as mock_staff:
            mock_staff.objects.filter.return_value.first.return_value = staff
            assert handler._staff_credentialed_name("s-1") == "Sara Sup"


class TestSubmitCosign:
    def test_404_when_no_pending_record(self):
        handler = _make_handler(
            json_body={"template": "teaching", "attestation_text": ""},
            path_params={"note_id": "note-1"},
        )
        with patch(f"{MODULE}.CoSignRecord") as mock_record:
            mock_record.objects.filter.return_value = []
            result = handler.submit_cosign()
            body, status = _parse(result[0])
            assert status == HTTPStatus.NOT_FOUND
            assert "no pending" in body["error"]

    def test_403_when_user_is_not_assigned_supervisor(self):
        handler = _make_handler(
            json_body={"template": "teaching", "attestation_text": ""},
            path_params={"note_id": "note-1"},
            user_id="not-the-supervisor",
        )
        record = MagicMock()
        record.supervisor_id = "sup-1"
        record.task_id = "task-1"
        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.NoteEffect") as mock_note_effect, \
             patch(f"{MODULE}.CustomCommand") as mock_custom_cmd, \
             patch(f"{MODULE}.AddTaskComment") as mock_add_comment:
            mock_record_cls.objects.filter.return_value = [record]
            result = handler.submit_cosign()
            body, status = _parse(result[0])
            assert status == HTTPStatus.FORBIDDEN
            assert "not authorized" in body["error"]
            # No chart writes attempted
            mock_note_effect.assert_not_called()
            mock_custom_cmd.assert_not_called()
            mock_add_comment.assert_not_called()
            record.save.assert_not_called()

    def test_400_when_attestation_empty_for_custom_template(self):
        handler = _make_handler(
            json_body={"template": "custom", "attestation_text": "   "},
            path_params={"note_id": "note-1"},
        )
        record = MagicMock()
        record.task_id = "task-1"
        record.supervisor_id = "sup-1"
        record.supervisee_id = "supe-1"
        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sara, MD"), \
             patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Lee Doc"):
            mock_record_cls.objects.filter.return_value = [record]
            result = handler.submit_cosign()
            body, status = _parse(result[0])
            assert status == HTTPStatus.BAD_REQUEST
            assert "attestation text is required" in body["error"]

    def test_happy_path_full_effect_chain(self):
        handler = _make_handler(
            json_body={
                "template": "teaching",
                "attestation_text": "",
                "additional_comments": "Reviewed thoroughly.",
            },
            path_params={"note_id": "note-1"},
        )
        record = MagicMock()
        record.task_id = "task-1"
        record.dbid = 1
        record.supervisor_id = "sup-1"
        record.supervisee_id = "supe-1"

        unlock_effect = MagicMock(name="unlock-effect")
        originate_effect = MagicMock(name="originate-effect")
        comment_effect = MagicMock(name="comment-effect")
        update_effect = MagicMock(name="update-effect")

        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.CoSignAddendum") as mock_addendum_cls, \
             patch(f"{MODULE}.CustomCommand") as mock_custom_cmd, \
             patch(f"{MODULE}.NoteEffect") as mock_note_effect, \
             patch(f"{MODULE}.AddTaskComment") as mock_add_comment, \
             patch(f"{MODULE}.UpdateTask") as mock_update_task, \
             patch(f"{MODULE}.uuid.uuid4", return_value="cmd-uuid"), \
             patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sara Sup, MD"), \
             patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Lee Doc"):
            mock_record_cls.objects.filter.return_value = [record]
            mock_note_effect.return_value.unlock.return_value = unlock_effect
            mock_custom_cmd.return_value.originate.return_value = originate_effect
            mock_add_comment.return_value.apply.return_value = comment_effect
            mock_update_task.return_value.apply.return_value = update_effect

            result = handler.submit_cosign()

            # JSONResponse last
            body, status = _parse(result[-1])
            assert status == HTTPStatus.OK
            assert body == {"status": "approved", "count": 1}

            # Record marked approved + addendum_text persisted
            assert record.status == "approved"
            assert record.cosigned_at is not None
            assert "Reviewed thoroughly." in record.addendum_text
            assert "Sara Sup, MD" in record.addendum_text
            record.save.assert_called_once()

            # AddTaskComment + UpdateTask emitted
            assert comment_effect in result
            assert update_effect in result
            mock_add_comment.assert_called_once()
            mock_update_task.assert_called_once()
            assert mock_update_task.call_args.kwargs["id"] == "task-1"

            # CoSignAddendum saved
            mock_addendum_cls.assert_called_once()
            addendum_kwargs = mock_addendum_cls.call_args.kwargs
            assert addendum_kwargs["note_id"] == "note-1"
            assert addendum_kwargs["supervisor_id"] == "sup-1"
            assert addendum_kwargs["supervisor_name"] == "Sara Sup, MD"
            mock_addendum_cls.return_value.save.assert_called_once()

            # CustomCommand built with attestation_review schema and html content
            cmd_kwargs = mock_custom_cmd.call_args.kwargs
            assert cmd_kwargs["note_uuid"] == "note-1"
            assert cmd_kwargs["schema_key"] == "attestation_review"
            assert cmd_kwargs["command_uuid"] == "cmd-uuid"
            assert "<br>" in cmd_kwargs["content"]
            assert "Reviewed thoroughly." in cmd_kwargs["content"]
            assert "Lee Doc" in cmd_kwargs["content"]

            # Effect chain: unlock then originate then LOCK_NOTE
            assert unlock_effect in result
            assert originate_effect in result
            unlock_idx = result.index(unlock_effect)
            originate_idx = result.index(originate_effect)
            assert unlock_idx < originate_idx

            # comment, update, unlock, originate, lock, json
            assert len(result) >= 6

    def test_skips_task_completion_when_task_id_empty(self):
        handler = _make_handler(
            json_body={"template": "personally_performed", "attestation_text": ""},
            path_params={"note_id": "note-1"},
        )
        record = MagicMock()
        record.task_id = ""
        record.supervisor_id = "sup-1"
        record.supervisee_id = "supe-1"

        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.CoSignAddendum"), \
             patch(f"{MODULE}.CustomCommand") as mock_custom_cmd, \
             patch(f"{MODULE}.NoteEffect") as mock_note_effect, \
             patch(f"{MODULE}.AddTaskComment") as mock_add_comment, \
             patch(f"{MODULE}.UpdateTask") as mock_update_task, \
             patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sara"), \
             patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Lee"):
            mock_record_cls.objects.filter.return_value = [record]
            mock_note_effect.return_value.unlock.return_value = MagicMock()
            mock_custom_cmd.return_value.originate.return_value = MagicMock()

            result = handler.submit_cosign()

            body, status = _parse(result[-1])
            assert status == HTTPStatus.OK
            mock_add_comment.assert_not_called()
            mock_update_task.assert_not_called()

    def test_500_when_chart_write_raises(self):
        handler = _make_handler(
            json_body={"template": "teaching", "attestation_text": ""},
            path_params={"note_id": "note-1"},
        )
        record = MagicMock()
        record.task_id = "task-1"
        record.supervisor_id = "sup-1"
        record.supervisee_id = "supe-1"

        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.CoSignAddendum") as mock_addendum_cls, \
             patch(f"{MODULE}.NoteEffect", side_effect=RuntimeError("boom")), \
             patch(f"{MODULE}.AddTaskComment") as mock_add_comment, \
             patch(f"{MODULE}.UpdateTask") as mock_update_task, \
             patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sara"), \
             patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Lee"):
            mock_record_cls.objects.filter.return_value = [record]
            result = handler.submit_cosign()
            body, status = _parse(result[0])
            assert status == HTTPStatus.INTERNAL_SERVER_ERROR
            assert "failed to write attestation" in body["error"]
            # Critical: chart-write failure must NOT leave the DB in an inconsistent state.
            # No record save, no addendum save, no task-side-effects emitted.
            record.save.assert_not_called()
            mock_addendum_cls.assert_not_called()
            mock_add_comment.assert_not_called()
            mock_update_task.assert_not_called()

    def test_html_escapes_user_supplied_content(self):
        handler = _make_handler(
            json_body={
                "template": "custom",
                "attestation_text": "<script>alert(1)</script>",
                "additional_comments": "<b>bold</b>",
            },
            path_params={"note_id": "note-1"},
        )
        record = MagicMock()
        record.task_id = ""
        record.supervisor_id = "sup-1"
        record.supervisee_id = "supe-1"

        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.CoSignAddendum"), \
             patch(f"{MODULE}.CustomCommand") as mock_custom_cmd, \
             patch(f"{MODULE}.NoteEffect") as mock_note_effect, \
             patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sara"), \
             patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Lee"):
            mock_record_cls.objects.filter.return_value = [record]
            mock_note_effect.return_value.unlock.return_value = MagicMock()
            mock_custom_cmd.return_value.originate.return_value = MagicMock()

            handler.submit_cosign()
            content = mock_custom_cmd.call_args.kwargs["content"]
            assert "&lt;script&gt;" in content
            assert "<script>" not in content
            assert "&lt;b&gt;bold&lt;/b&gt;" in content

    def test_multiparagraph_attestation_converts_newlines_to_br(self):
        # If the supervisor writes multi-paragraph custom text, the \n breaks
        # must convert to <br> so Canvas's custom command renderer preserves
        # the paragraph structure (raw \n collapses to a single line in HTML).
        handler = _make_handler(
            json_body={
                "template": "custom",
                "attestation_text": "First paragraph.\n\nSecond paragraph.",
                "additional_comments": "",
            },
            path_params={"note_id": "note-1"},
        )
        record = MagicMock()
        record.task_id = ""
        record.supervisor_id = "sup-1"
        record.supervisee_id = "supe-1"

        with patch(f"{MODULE}.CoSignRecord") as mock_record_cls, \
             patch(f"{MODULE}.CoSignAddendum"), \
             patch(f"{MODULE}.CustomCommand") as mock_custom_cmd, \
             patch(f"{MODULE}.NoteEffect") as mock_note_effect, \
             patch.object(SupervisorCoSignAPI, "_staff_credentialed_name", return_value="Sara"), \
             patch.object(SupervisorCoSignAPI, "_staff_name", return_value="Lee"):
            mock_record_cls.objects.filter.return_value = [record]
            mock_note_effect.return_value.unlock.return_value = MagicMock()
            mock_custom_cmd.return_value.originate.return_value = MagicMock()

            handler.submit_cosign()
            content = mock_custom_cmd.call_args.kwargs["content"]
            assert "First paragraph.<br><br>Second paragraph." in content
            assert "First paragraph.\n\nSecond paragraph." not in content


class TestComplianceReport:
    def test_date_filters_use_date_lookup_not_raw_datetime_lte(self):
        # selected_at__lte against a DateTimeField parses end="2026-05-31" as
        # midnight at the START of May 31, silently excluding records from
        # later that day. Switching to selected_at__date__lte fixes that -
        # end-of-month reports now include the full last day.
        handler = _make_handler(
            query_params={"start": "2026-05-01", "end": "2026-05-31"},
            user_id="sup-1",
        )
        with patch(f"{MODULE}.CoSignRecord") as mock_record:
            chain = mock_record.objects.filter.return_value
            chain.filter.return_value = chain
            chain.values.return_value = []
            handler.compliance_report()
            filter_calls = chain.filter.call_args_list
            kwargs_seen = [c.kwargs for c in filter_calls]
            assert any("selected_at__date__gte" in k for k in kwargs_seen)
            assert any("selected_at__date__lte" in k for k in kwargs_seen)
            for k in kwargs_seen:
                assert "selected_at__gte" not in k
                assert "selected_at__lte" not in k

    def test_datetime_fields_serialized_to_iso(self):
        # JSONResponse uses stock json.dumps with no datetime encoder, so
        # records returned by qs.values() with raw datetime/date values would
        # 500 if not converted first. The handler must serialize all temporal
        # fields to ISO strings before they hit JSONResponse.
        from datetime import date, datetime, timezone
        handler = _make_handler(query_params={}, user_id="sup-1")
        rows = [
            {
                "note_id": "n1", "supervisee_id": "supe-1", "supervisor_id": "sup-1",
                "status": "approved",
                "selected_at": datetime(2026, 5, 1, 14, 30, tzinfo=timezone.utc),
                "cosigned_at": datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
                "due_date": date(2026, 5, 4),
            },
        ]
        with patch(f"{MODULE}.CoSignRecord") as mock_record:
            chain = mock_record.objects.filter.return_value
            chain.filter.return_value = chain
            chain.values.return_value = rows
            # This call would raise TypeError if datetimes weren't pre-serialized
            result = handler.compliance_report()
            body, status = _parse(result[0])
            assert status == HTTPStatus.OK
            r = body["records"][0]
            assert r["selected_at"] == "2026-05-01T14:30:00+00:00"
            assert r["cosigned_at"] == "2026-05-02T10:00:00+00:00"
            assert r["due_date"] == "2026-05-04"


    def test_empty_returns_empty_summary(self):
        handler = _make_handler(query_params={}, user_id="sup-1")
        with patch(f"{MODULE}.CoSignRecord") as mock_record:
            chain = mock_record.objects.filter.return_value
            chain.values.return_value = []
            result = handler.compliance_report()
            body, status = _parse(result[0])
            assert status == HTTPStatus.OK
            assert body["summary"] == {}
            assert body["records"] == []
            # Initial filter scopes by requester
            mock_record.objects.filter.assert_called_once_with(supervisor_id="sup-1")

    def test_scopes_to_requesting_supervisor(self):
        handler = _make_handler(
            query_params={"start": "2026-01-01", "end": "2026-12-31"},
            user_id="sup-42",
        )
        rows = [
            {
                "note_id": "n1",
                "supervisee_id": "supe-1",
                "supervisor_id": "sup-42",
                "status": "approved",
                "selected_at": "2026-05-01",
                "cosigned_at": "2026-05-02",
                "due_date": "2026-05-04",
            },
            {
                "note_id": "n2",
                "supervisee_id": "supe-1",
                "supervisor_id": "sup-42",
                "status": "pending",
                "selected_at": "2026-05-03",
                "cosigned_at": None,
                "due_date": "2026-05-06",
            },
            {
                "note_id": "n3",
                "supervisee_id": "supe-2",
                "supervisor_id": "sup-42",
                "status": "approved",
                "selected_at": "2026-05-05",
                "cosigned_at": "2026-05-05",
                "due_date": "2026-05-08",
            },
        ]
        with patch(f"{MODULE}.CoSignRecord") as mock_record:
            chain = mock_record.objects.filter.return_value
            chain.filter.return_value = chain
            chain.values.return_value = rows
            result = handler.compliance_report()

            body, status = _parse(result[0])
            assert status == HTTPStatus.OK
            # Scoped to requester
            mock_record.objects.filter.assert_called_once_with(supervisor_id="sup-42")
            assert body["summary"]["supe-1"] == {
                "total": 2,
                "approved": 1,
                "pending": 1,
                "pct_cosigned": 50.0,
            }
            assert body["summary"]["supe-2"] == {
                "total": 1,
                "approved": 1,
                "pending": 0,
                "pct_cosigned": 100.0,
            }
            # start + end date filters applied on top of supervisor scope
            assert chain.filter.call_count == 2
