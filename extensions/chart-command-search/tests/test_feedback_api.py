import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

from chart_command_search.handlers.feedback_api import (
    _MAX_COMMENT_LENGTH,
    _MAX_QUERY_LENGTH,
    _MAX_SUMMARY_LENGTH,
    FeedbackQueryAPI,
    FeedbackSubmitAPI,
)

VALID_PATIENT_ID = "12345678-1234-1234-1234-123456789abc"
VALID_STAFF_UUID = "abcdef01-2345-6789-abcd-ef0123456789"


def _make_request(
    body: dict[str, Any] | None = None,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    req = MagicMock()
    req.body = json.dumps(body if body is not None else {}).encode()
    req.query_params = query_params or {}
    req.headers = headers or {}
    return req


def _get_json(responses: list[Any]) -> dict[str, Any]:
    assert len(responses) == 1
    return json.loads(getattr(responses[0], "content"))


def _get_status(responses: list[Any]) -> int:
    assert len(responses) == 1
    return responses[0].status_code


def _make_mock_staff() -> MagicMock:
    staff = MagicMock()
    staff.id = VALID_STAFF_UUID
    staff.dbid = 42
    staff.first_name = "Jane"
    staff.last_name = "Doe"
    return staff


def _make_submit_handler(
    body: dict[str, Any] | None = None,
    secrets: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> FeedbackSubmitAPI:
    handler = FeedbackSubmitAPI.__new__(FeedbackSubmitAPI)
    handler.request = _make_request(body=body, headers=headers)
    handler.secrets = secrets or {}
    return handler


def _make_query_handler(
    query_params: dict[str, str] | None = None,
    secrets: dict[str, str] | None = None,
) -> FeedbackQueryAPI:
    handler = FeedbackQueryAPI.__new__(FeedbackQueryAPI)
    handler.request = _make_request(query_params=query_params)
    handler.secrets = secrets or {"FEEDBACK_API_KEY": "test-key-123"}
    return handler


def _valid_submit_body() -> dict[str, Any]:
    return {
        "patient_id": VALID_PATIENT_ID,
        "query": "What medications is the patient on?",
        "answer_summary": "The patient takes Lisinopril and Metformin.",
        "answer_key_findings": [{"type": "info", "text": "Two active meds"}],
        "rating": "up",
        "comment": "Very helpful",
    }


# ═══════════════════════════════════════════════════════════════════════════
# FeedbackSubmitAPI POST validation tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedbackSubmitValidation:
    def test_invalid_json_body(self) -> None:
        handler = FeedbackSubmitAPI.__new__(FeedbackSubmitAPI)
        handler.request = MagicMock()
        handler.request.body = b"not json"
        handler.secrets = {}
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "Invalid JSON" in _get_json(result)["error"]

    def test_missing_patient_id(self) -> None:
        body = _valid_submit_body()
        del body["patient_id"]
        handler = _make_submit_handler(body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "patient_id" in _get_json(result)["error"]

    def test_invalid_patient_id_format(self) -> None:
        body = _valid_submit_body()
        body["patient_id"] = "not-a-uuid"
        handler = _make_submit_handler(body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "patient_id" in _get_json(result)["error"]

    def test_missing_query(self) -> None:
        body = _valid_submit_body()
        body["query"] = ""
        handler = _make_submit_handler(body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "query" in _get_json(result)["error"]

    def test_query_exceeds_max_length(self) -> None:
        body = _valid_submit_body()
        body["query"] = "x" * (_MAX_QUERY_LENGTH + 1)
        handler = _make_submit_handler(body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "maximum length" in _get_json(result)["error"]

    def test_missing_answer_summary(self) -> None:
        body = _valid_submit_body()
        body["answer_summary"] = ""
        handler = _make_submit_handler(body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "answer_summary" in _get_json(result)["error"]

    def test_invalid_rating(self) -> None:
        body = _valid_submit_body()
        body["rating"] = "maybe"
        handler = _make_submit_handler(body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST
        assert "rating" in _get_json(result)["error"]

    def test_missing_staff_header(self) -> None:
        handler = _make_submit_handler(body=_valid_submit_body(), headers={})
        result = handler.post()
        assert _get_status(result) == HTTPStatus.UNAUTHORIZED

    def test_rating_case_insensitive(self) -> None:
        body = _valid_submit_body()
        body["rating"] = "UP"
        handler = _make_submit_handler(
            body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.CREATED

    def test_answer_summary_truncated_at_max(self) -> None:
        body = _valid_submit_body()
        body["answer_summary"] = "s" * (_MAX_SUMMARY_LENGTH + 500)
        handler = _make_submit_handler(
            body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.CREATED
        call_kwargs = mock_sf.objects.create.call_args[1]
        assert len(call_kwargs["answer_summary"]) == _MAX_SUMMARY_LENGTH

    def test_comment_truncated_at_max(self) -> None:
        body = _valid_submit_body()
        body["comment"] = "c" * (_MAX_COMMENT_LENGTH + 100)
        handler = _make_submit_handler(
            body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.CREATED
        call_kwargs = mock_sf.objects.create.call_args[1]
        assert len(call_kwargs["comment"]) == _MAX_COMMENT_LENGTH

    def test_non_list_key_findings_defaults_to_empty(self) -> None:
        body = _valid_submit_body()
        body["answer_key_findings"] = "not a list"
        handler = _make_submit_handler(
            body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.CREATED
        call_kwargs = mock_sf.objects.create.call_args[1]
        assert call_kwargs["answer_key_findings"] == []


# ═══════════════════════════════════════════════════════════════════════════
# FeedbackSubmitAPI POST success path
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedbackSubmitSuccess:
    def test_successful_submission(self) -> None:
        handler = _make_submit_handler(
            body=_valid_submit_body(),
            headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        mock_staff = _make_mock_staff()

        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = mock_staff
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()

        assert _get_status(result) == HTTPStatus.CREATED
        data = _get_json(result)
        assert data["status"] == "created"
        assert "feedback_id" in data
        assert len(data["feedback_id"]) == 36

        call_kwargs = mock_sf.objects.create.call_args[1]
        assert call_kwargs["patient_id"] == VALID_PATIENT_ID
        assert call_kwargs["staff"] == mock_staff
        assert call_kwargs["rating"] == "up"
        assert call_kwargs["query"] == "What medications is the patient on?"
        assert call_kwargs["comment"] == "Very helpful"

    def test_submission_with_empty_comment(self) -> None:
        body = _valid_submit_body()
        body["comment"] = ""
        handler = _make_submit_handler(
            body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.CREATED

    def test_thumbs_down_rating(self) -> None:
        body = _valid_submit_body()
        body["rating"] = "down"
        body["comment"] = "Not relevant"
        handler = _make_submit_handler(
            body=body, headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.return_value = MagicMock()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.CREATED
        call_kwargs = mock_sf.objects.create.call_args[1]
        assert call_kwargs["rating"] == "down"


# ═══════════════════════════════════════════════════════════════════════════
# FeedbackSubmitAPI POST error paths
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedbackSubmitErrors:
    def test_staff_not_found(self) -> None:
        handler = _make_submit_handler(
            body=_valid_submit_body(),
            headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs:
            mock_cs.DoesNotExist = type("DoesNotExist", (Exception,), {})
            mock_cs.objects.get.side_effect = mock_cs.DoesNotExist()
            result = handler.post()
        assert _get_status(result) == HTTPStatus.NOT_FOUND

    def test_db_create_failure(self) -> None:
        handler = _make_submit_handler(
            body=_valid_submit_body(),
            headers={"canvas-logged-in-user-id": VALID_STAFF_UUID},
        )
        with patch("chart_command_search.handlers.feedback_api.CustomStaff") as mock_cs, \
             patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_cs.objects.get.return_value = _make_mock_staff()
            mock_sf.objects.create.side_effect = RuntimeError("DB write failed")
            result = handler.post()
        assert _get_status(result) == HTTPStatus.INTERNAL_SERVER_ERROR


# ═══════════════════════════════════════════════════════════════════════════
# FeedbackQueryAPI authentication
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedbackQueryAuth:
    def test_auth_succeeds_with_correct_key(self) -> None:
        handler = _make_query_handler(secrets={"FEEDBACK_API_KEY": "my-secret"})
        creds = MagicMock()
        creds.key = "my-secret"
        assert handler.authenticate(creds) is True

    def test_auth_fails_with_wrong_key(self) -> None:
        handler = _make_query_handler(secrets={"FEEDBACK_API_KEY": "my-secret"})
        creds = MagicMock()
        creds.key = "wrong-key"
        with pytest.raises(InvalidCredentialsError):
            handler.authenticate(creds)

    def test_auth_fails_when_secret_not_configured(self) -> None:
        handler = _make_query_handler(secrets={})
        creds = MagicMock()
        creds.key = "any-key"
        with pytest.raises(InvalidCredentialsError):
            handler.authenticate(creds)


# ═══════════════════════════════════════════════════════════════════════════
# FeedbackQueryAPI GET list mode
# ═══════════════════════════════════════════════════════════════════════════


def _make_mock_feedback(
    feedback_id: str = "fb-001",
    patient_id: str = VALID_PATIENT_ID,
    rating: str = "up",
    query: str = "Test query",
    answer_summary: str = "Test answer",
    comment: str = "",
) -> MagicMock:
    fb = MagicMock()
    fb.feedback_id = feedback_id
    fb.patient_id = patient_id
    fb.rating = rating
    fb.query = query
    fb.answer_summary = answer_summary
    fb.answer_key_findings = []
    fb.comment = comment
    fb.created_at = MagicMock()
    fb.created_at.isoformat.return_value = "2026-04-01T10:30:00+00:00"
    staff = MagicMock()
    staff.id = VALID_STAFF_UUID
    staff.first_name = "Jane"
    staff.last_name = "Doe"
    fb.staff = staff
    return fb


class TestFeedbackQueryList:
    def test_list_returns_results(self) -> None:
        handler = _make_query_handler(query_params={"mode": "list"})
        mock_fb = _make_mock_feedback()

        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            qs = MagicMock()
            qs.count.return_value = 1
            qs.select_related.return_value = qs
            qs.order_by.return_value = [mock_fb]
            mock_sf.objects.all.return_value = qs
            qs.filter.return_value = qs

            result = handler.get()

        data = _get_json(result)
        assert data["total"] == 1
        assert data["count"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["feedback_id"] == "fb-001"
        assert data["results"][0]["staff_name"] == "Jane Doe"

    def test_list_filters_by_patient_id(self) -> None:
        handler = _make_query_handler(
            query_params={"mode": "list", "patient_id": VALID_PATIENT_ID},
        )
        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            qs = MagicMock()
            qs.count.return_value = 0
            qs.select_related.return_value = qs
            qs.order_by.return_value = []
            mock_sf.objects.all.return_value = qs
            qs.filter.return_value = qs

            result = handler.get()

        qs.filter.assert_any_call(patient_id=VALID_PATIENT_ID)
        data = _get_json(result)
        assert data["total"] == 0

    def test_list_rejects_invalid_patient_id(self) -> None:
        handler = _make_query_handler(
            query_params={"patient_id": "bad-id"},
        )
        with patch("chart_command_search.handlers.feedback_api.SearchFeedback"):
            result = handler.get()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST

    def test_list_invalid_from_date(self) -> None:
        handler = _make_query_handler(
            query_params={"from_date": "not-a-date"},
        )
        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            mock_sf.objects.all.return_value = MagicMock()
            result = handler.get()
        assert _get_status(result) == HTTPStatus.BAD_REQUEST

    def test_list_default_mode(self) -> None:
        handler = _make_query_handler(query_params={})
        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            qs = MagicMock()
            qs.count.return_value = 0
            qs.select_related.return_value = qs
            qs.order_by.return_value = []
            mock_sf.objects.all.return_value = qs
            qs.filter.return_value = qs

            result = handler.get()

        data = _get_json(result)
        assert "results" in data


# ═══════════════════════════════════════════════════════════════════════════
# FeedbackQueryAPI GET stats mode
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedbackQueryStats:
    def test_stats_returns_counts_and_percentages(self) -> None:
        handler = _make_query_handler(query_params={"mode": "stats"})

        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            qs = MagicMock()
            qs.aggregate.return_value = {"total": 10, "up_count": 7, "down_count": 3}
            mock_sf.objects.all.return_value = qs

            result = handler.get()

        data = _get_json(result)
        assert data["total"] == 10
        assert data["thumbs_up"] == 7
        assert data["thumbs_down"] == 3
        assert data["thumbs_up_pct"] == 70.0
        assert data["thumbs_down_pct"] == 30.0

    def test_stats_zero_total(self) -> None:
        handler = _make_query_handler(query_params={"mode": "stats"})

        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            qs = MagicMock()
            qs.aggregate.return_value = {"total": 0, "up_count": 0, "down_count": 0}
            mock_sf.objects.all.return_value = qs

            result = handler.get()

        data = _get_json(result)
        assert data["total"] == 0
        assert data["thumbs_up_pct"] == 0.0
        assert data["thumbs_down_pct"] == 0.0

    def test_stats_includes_applied_filters(self) -> None:
        handler = _make_query_handler(
            query_params={"mode": "stats", "patient_id": VALID_PATIENT_ID, "rating": "up"},
        )

        with patch("chart_command_search.handlers.feedback_api.SearchFeedback") as mock_sf:
            qs = MagicMock()
            qs.filter.return_value = qs
            qs.aggregate.return_value = {"total": 5, "up_count": 5, "down_count": 0}
            mock_sf.objects.all.return_value = qs

            result = handler.get()

        data = _get_json(result)
        assert data["filters_applied"]["patient_id"] == VALID_PATIENT_ID
        assert data["filters_applied"]["rating"] == "up"
        assert data["total"] == 5
        assert data["thumbs_up"] == 5
        assert data["thumbs_down"] == 0
