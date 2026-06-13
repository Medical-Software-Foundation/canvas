from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from canvas_sdk.events import EventType

from imaging_fhir_poc.handlers.imaging_review_fhir import ImagingReviewFhirHandler


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    return {
        "CLIENT_ID": "test-client-id",
        "CLIENT_SECRET": "test-client-secret",
        "FHIR_BASE_URL": "https://fumage-example.canvasmedical.com",
    }


@pytest.fixture
def mock_event_context() -> dict[str, object]:
    return {
        "patient": {"id": "patient-123"},
        "fields": {
            "report": [
                {
                    "text": "Bone and/or joint imaging; whole body",
                    "value": "12345",
                    "annotations": ["Jan 29, 2025"],
                }
            ],
            "message_to_patient": "",
            "communication_method": {"value": "DL", "text": "Delegate letter"},
            "internal_comment": "",
        },
        "note": {"uuid": "note-uuid-456"},
    }


def test_handler_responds_to_correct_event() -> None:
    """Test that the handler responds to IMAGING_REVIEW_COMMAND__POST_COMMIT."""
    expected_event = EventType.Name(EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT)
    assert expected_event in ImagingReviewFhirHandler.RESPONDS_TO


def test_handler_extracts_patient_id_and_report_timestamp(
    mock_event_context: dict[str, object],
) -> None:
    """Test that the handler extracts patient ID and report timestamp from context."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context

    handler = ImagingReviewFhirHandler(event=mock_event)
    timestamp = datetime(2026, 1, 15, 10, 30, 0)

    with patch.object(handler, "_extract_report_dbid", return_value=12345):
        with patch.object(handler, "_get_report_timestamp", return_value=timestamp):
            with patch.object(handler, "_fetch_document_references") as mock_fetch:
                handler.compute()
                mock_fetch.assert_called_once_with("patient-123", timestamp)


def test_extract_report_dbid_from_context(
    mock_event_context: dict[str, object],
) -> None:
    """Test that _extract_report_dbid extracts the dbid from context."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context

    handler = ImagingReviewFhirHandler(event=mock_event)

    result = handler._extract_report_dbid(mock_event_context)

    assert result == 12345


def test_extract_report_dbid_returns_none_for_empty_reports() -> None:
    """Test that _extract_report_dbid returns None when reports list is empty."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = {"fields": {"report": []}}

    handler = ImagingReviewFhirHandler(event=mock_event)

    result = handler._extract_report_dbid({"fields": {"report": []}})

    assert result is None


def test_extract_report_dbid_returns_none_for_missing_value() -> None:
    """Test that _extract_report_dbid returns None when value is missing."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = {"fields": {"report": [{"text": "test"}]}}

    handler = ImagingReviewFhirHandler(event=mock_event)

    result = handler._extract_report_dbid({"fields": {"report": [{"text": "test"}]}})

    assert result is None


def test_handler_returns_empty_effects_when_no_patient_id() -> None:
    """Test that the handler returns empty effects when no patient ID is present."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = {"fields": {}, "note": {"uuid": "note-uuid"}}

    handler = ImagingReviewFhirHandler(event=mock_event)
    effects = handler.compute()

    assert effects == []


def test_handler_logs_error_when_secrets_missing(
    mock_event_context: dict[str, object],
) -> None:
    """Test that the handler logs an error when secrets are missing."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context
    mock_event.secrets = {}

    handler = ImagingReviewFhirHandler(event=mock_event)

    with patch("imaging_fhir_poc.handlers.imaging_review_fhir.log") as mock_log:
        handler._fetch_document_references("patient-123", None)
        mock_log.error.assert_called_with(
            "Missing required secrets: FHIR_BASE_URL, CLIENT_ID, or CLIENT_SECRET"
        )


def test_handler_makes_oauth_request(
    mock_event_context: dict[str, object],
    mock_secrets: dict[str, str],
) -> None:
    """Test that the handler makes an OAuth token request to correct URL."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context
    mock_event.secrets = mock_secrets

    handler = ImagingReviewFhirHandler(event=mock_event)

    with patch("imaging_fhir_poc.handlers.imaging_review_fhir.Http") as mock_http_class:
        mock_http = Mock()
        mock_http_class.return_value = mock_http

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": "test-token"}
        mock_http.post.return_value = mock_response

        # FHIR URL: https://fumage-example.canvasmedical.com
        # Token URL should be: https://example.canvasmedical.com/auth/token/
        token = handler._get_oauth_token(
            mock_secrets["FHIR_BASE_URL"],
            mock_secrets["CLIENT_ID"],
            mock_secrets["CLIENT_SECRET"],
        )

        assert token == "test-token"
        call_args = mock_http.post.call_args
        token_url = call_args[0][0]
        assert token_url == "https://example.canvasmedical.com/auth/token/"


def test_handler_makes_fhir_search_request_without_timestamp(
    mock_event_context: dict[str, object],
    mock_secrets: dict[str, str],
) -> None:
    """Test that the handler makes a FHIR search request without date filter."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context
    mock_event.secrets = mock_secrets

    handler = ImagingReviewFhirHandler(event=mock_event)

    fhir_bundle = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 2,
        "entry": [
            {"resource": {"resourceType": "DocumentReference", "id": "doc-1"}},
            {"resource": {"resourceType": "DocumentReference", "id": "doc-2"}},
        ],
    }

    with patch("imaging_fhir_poc.handlers.imaging_review_fhir.Http") as mock_http_class:
        mock_http = Mock()
        mock_http_class.return_value = mock_http

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = fhir_bundle
        mock_http.get.return_value = mock_response

        with patch("imaging_fhir_poc.handlers.imaging_review_fhir.log") as mock_log:
            handler._search_document_references(
                mock_secrets["FHIR_BASE_URL"],
                "test-token",
                "patient-123",
                None,
            )

            mock_log.info.assert_any_call(
                "FHIR DocumentReference search returned 2 results"
            )
            call_args = mock_http.get.call_args
            url = call_args[0][0]
            assert "date=" not in url


def test_handler_makes_fhir_search_request_with_timestamp_range(
    mock_event_context: dict[str, object],
    mock_secrets: dict[str, str],
) -> None:
    """Test that the handler includes +/- 1 minute range when timestamp is provided."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context
    mock_event.secrets = mock_secrets

    handler = ImagingReviewFhirHandler(event=mock_event)

    fhir_bundle = {"resourceType": "Bundle", "type": "searchset", "total": 1, "entry": []}

    with patch("imaging_fhir_poc.handlers.imaging_review_fhir.Http") as mock_http_class:
        mock_http = Mock()
        mock_http_class.return_value = mock_http

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = fhir_bundle
        mock_http.get.return_value = mock_response

        report_timestamp = datetime(2026, 1, 15, 10, 30, 0)
        handler._search_document_references(
            mock_secrets["FHIR_BASE_URL"],
            "test-token",
            "patient-123",
            report_timestamp,
        )

        call_args = mock_http.get.call_args
        url = call_args[0][0]
        # Should be +/- 1 minute: 10:29:00 to 10:31:00
        assert "date=ge2026-01-15T10%3A29%3A00" in url
        assert "date=le2026-01-15T10%3A31%3A00" in url


def test_get_report_timestamp_returns_created(
    mock_event_context: dict[str, object],
) -> None:
    """Test that _get_report_timestamp returns the created timestamp."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context

    handler = ImagingReviewFhirHandler(event=mock_event)

    mock_report = Mock()
    mock_report.created = datetime(2026, 1, 12, 10, 30, 45)

    with patch(
        "imaging_fhir_poc.handlers.imaging_review_fhir.ImagingReport"
    ) as mock_imaging_report:
        mock_imaging_report.objects.get.return_value = mock_report

        result = handler._get_report_timestamp(12345)

        assert result == datetime(2026, 1, 12, 10, 30, 45)
        mock_imaging_report.objects.get.assert_called_once_with(dbid=12345)


def test_get_report_timestamp_returns_none_when_no_created(
    mock_event_context: dict[str, object],
) -> None:
    """Test that _get_report_timestamp returns None when created is not set."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context

    handler = ImagingReviewFhirHandler(event=mock_event)

    mock_report = Mock()
    mock_report.created = None

    with patch(
        "imaging_fhir_poc.handlers.imaging_review_fhir.ImagingReport"
    ) as mock_imaging_report:
        mock_imaging_report.objects.get.return_value = mock_report

        result = handler._get_report_timestamp(12345)

        assert result is None


def test_get_report_timestamp_returns_none_when_not_found(
    mock_event_context: dict[str, object],
) -> None:
    """Test that _get_report_timestamp returns None when report not found."""
    mock_event = Mock()
    mock_event.type = EventType.IMAGING_REVIEW_COMMAND__POST_COMMIT
    mock_event.context = mock_event_context

    handler = ImagingReviewFhirHandler(event=mock_event)

    with patch(
        "imaging_fhir_poc.handlers.imaging_review_fhir.ImagingReport"
    ) as mock_imaging_report:
        mock_imaging_report.DoesNotExist = Exception
        mock_imaging_report.objects.get.side_effect = mock_imaging_report.DoesNotExist

        with patch("imaging_fhir_poc.handlers.imaging_review_fhir.log"):
            result = handler._get_report_timestamp(99999)

        assert result is None
