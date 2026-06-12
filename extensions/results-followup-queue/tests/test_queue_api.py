"""Tests for results_followup_queue.handlers.queue_api."""

from __future__ import annotations

import datetime
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.test_utils.factories import (
    ImagingOrderFactory,
    ImagingReportFactory,
    ImagingReviewFactory,
    LabOrderFactory,
    LabReportFactory,
    LabReviewFactory,
    LabTestFactory,
    LabValueFactory,
    PatientFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.common import DocumentReviewMode

from results_followup_queue.handlers.queue_api import (
    QueueAPI,
    _days_pending,
    _is_abnormal,
    _lab_result_name,
    _patient_name,
    _sort_key,
)

MODULE = "results_followup_queue.handlers.queue_api"
TODAY = datetime.date(2026, 6, 12)


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_handler(
    staff_uuid: str = "staff-uuid-001",
    *,
    include_header: bool = True,
) -> QueueAPI:
    """Build a QueueAPI handler with a fully mocked request."""
    handler = QueueAPI(MagicMock())
    handler.request = MagicMock()
    handler.request.headers = (
        {"canvas-logged-in-user-id": staff_uuid} if include_header else {}
    )
    return handler


def _make_lab_for(
    staff: Any,
    *,
    test_name: str = "Complete Blood Count",
    days_ago: int = 3,
    abnormal: bool = False,
    review: Any = None,
    junked: bool = False,
    deleted: bool = False,
    review_mode: str = DocumentReviewMode.REVIEW_REQUIRED,
    requires_signature: bool = False,
    patient: Any = None,
) -> Any:
    """Create a LabReport attributed to ``staff`` via test → order → provider."""
    performed = datetime.datetime(
        TODAY.year, TODAY.month, TODAY.day, 8, 0, tzinfo=datetime.timezone.utc
    ) - datetime.timedelta(days=days_ago)
    report = LabReportFactory.create(
        patient=patient or PatientFactory.create(),
        review=review,
        junked=junked,
        deleted=deleted,
        review_mode=review_mode,
        requires_signature=requires_signature,
        date_performed=performed,
    )
    order = LabOrderFactory.create(ordering_provider=staff)
    LabTestFactory.create(report=report, order=order, ontology_test_name=test_name)
    LabValueFactory.create(report=report, abnormal_flag="H" if abnormal else "")
    return report


def _make_imaging_for(
    staff: Any,
    *,
    name: str = "Chest X-Ray",
    days_ago: int = 5,
    review: Any = None,
    junked: bool = False,
    review_mode: str = DocumentReviewMode.REVIEW_REQUIRED,
    requires_signature: bool = False,
    patient: Any = None,
) -> Any:
    """Create an ImagingReport attributed to ``staff`` via order → provider."""
    order = ImagingOrderFactory.create(ordering_provider=staff)
    return ImagingReportFactory.create(
        patient=patient or PatientFactory.create(),
        order=order,
        review=review,
        junked=junked,
        review_mode=review_mode,
        requires_signature=requires_signature,
        name=name,
        result_date=TODAY - datetime.timedelta(days=days_ago),
    )


def _data(handler: QueueAPI) -> list[dict[str, Any]]:
    """Call get_data() (with the clock pinned to TODAY) and return the rows."""
    with patch(f"{MODULE}.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.datetime(
            TODAY.year, TODAY.month, TODAY.day, 12, 0, tzinfo=datetime.timezone.utc
        )
        result = handler.get_data()
    assert result[0].status_code == HTTPStatus.OK
    rows: list[dict[str, Any]] = json.loads(result[0].content)["results"]
    return rows


# ── Static asset routes ───────────────────────────────────────────────────


def test_get_index_returns_html() -> None:
    """GET / must return 200 with HTML content."""
    handler = _make_handler()
    with patch(f"{MODULE}.render_to_string", return_value="<html>Queue</html>"):
        result = handler.get_index()

    assert len(result) == 1
    resp = result[0]
    assert resp.status_code == HTTPStatus.OK
    body = resp.content.decode() if isinstance(resp.content, bytes) else resp.content
    assert "Queue" in body


def test_get_index_passes_cache_bust_context() -> None:
    """GET / must pass a numeric cache_bust into the template context."""
    handler = _make_handler()
    captured: dict[str, Any] = {}

    def capture_render(
        template: str, context: dict | None = None, **kwargs: Any
    ) -> str:
        captured.update(context or {})
        return "<html></html>"

    with patch(f"{MODULE}.render_to_string", side_effect=capture_render):
        handler.get_index()

    assert captured["cache_bust"].isdigit()


def test_get_js_returns_javascript() -> None:
    """GET /main.js must return application/javascript."""
    handler = _make_handler()
    with patch(f"{MODULE}.render_to_string", return_value="console.log('ok');"):
        result = handler.get_js()

    assert result[0].status_code == HTTPStatus.OK
    assert result[0].headers.get("Content-Type") == "application/javascript"


def test_get_css_returns_css() -> None:
    """GET /styles.css must return text/css."""
    handler = _make_handler()
    with patch(f"{MODULE}.render_to_string", return_value="body{}"):
        result = handler.get_css()

    assert result[0].status_code == HTTPStatus.OK
    assert result[0].headers.get("Content-Type") == "text/css"


# ── /data – auth ──────────────────────────────────────────────────────────


def test_get_data_missing_staff_uuid_returns_400() -> None:
    """GET /data without the staff header must return 400, not an empty list."""
    handler = _make_handler(include_header=False)
    result = handler.get_data()

    assert result[0].status_code == HTTPStatus.BAD_REQUEST
    assert "error" in json.loads(result[0].content)


# ── /data – integration (real DB via factories) ──────────────────────────


@pytest.mark.django_db
def test_get_data_empty_queue_returns_empty_list() -> None:
    """A provider with nothing to review gets an empty results list."""
    staff = StaffFactory.create()
    rows = _data(_make_handler(str(staff.id)))
    assert rows == []


@pytest.mark.django_db
def test_get_data_returns_lab_and_imaging_rows() -> None:
    """Both a pending lab and a pending imaging result appear for the provider."""
    staff = StaffFactory.create()
    _make_lab_for(staff, test_name="Complete Blood Count")
    _make_imaging_for(staff, name="Chest X-Ray")

    rows = _data(_make_handler(str(staff.id)))

    types = {row["type"] for row in rows}
    names = {row["name"] for row in rows}
    assert types == {"lab", "imaging"}
    assert names == {"Complete Blood Count", "Chest X-Ray"}


@pytest.mark.django_db
def test_get_data_lab_row_has_expected_fields() -> None:
    """A lab row carries the full result-row contract."""
    staff = StaffFactory.create()
    patient = PatientFactory.create(first_name="Jane", last_name="Doe")
    _make_lab_for(
        staff,
        patient=patient,
        test_name="Lipid Panel",
        days_ago=7,
        abnormal=True,
        requires_signature=True,
    )

    rows = _data(_make_handler(str(staff.id)))
    assert len(rows) == 1
    row = rows[0]
    assert row["patient_key"] == str(patient.id)
    assert row["patient_name"] == "Jane Doe"
    assert row["type"] == "lab"
    assert row["name"] == "Lipid Panel"
    assert row["result_date"] == "2026-06-05"
    assert row["days_pending"] == 7
    assert row["abnormal"] is True
    assert row["requires_signature"] is True


@pytest.mark.django_db
def test_get_data_excludes_other_providers_results() -> None:
    """Results ordered by a different provider must not appear."""
    me = StaffFactory.create()
    someone_else = StaffFactory.create()
    _make_lab_for(someone_else)
    _make_imaging_for(someone_else)

    rows = _data(_make_handler(str(me.id)))
    assert rows == []


@pytest.mark.django_db
def test_get_data_excludes_reviewed_results() -> None:
    """A lab with a review record is no longer pending."""
    staff = StaffFactory.create()
    _make_lab_for(staff, review=LabReviewFactory.create())
    _make_imaging_for(staff, review=ImagingReviewFactory.create())

    rows = _data(_make_handler(str(staff.id)))
    assert rows == []


@pytest.mark.django_db
def test_get_data_excludes_junked_results() -> None:
    """Junked lab and imaging results are excluded."""
    staff = StaffFactory.create()
    _make_lab_for(staff, junked=True)
    _make_imaging_for(staff, junked=True)

    rows = _data(_make_handler(str(staff.id)))
    assert rows == []


@pytest.mark.django_db
def test_get_data_excludes_deleted_and_entered_in_error_labs() -> None:
    """Deleted lab reports are excluded (imaging has no deleted flag)."""
    staff = StaffFactory.create()
    _make_lab_for(staff, deleted=True)

    rows = _data(_make_handler(str(staff.id)))
    assert rows == []


@pytest.mark.django_db
def test_get_data_excludes_review_not_required() -> None:
    """Results flagged 'review not required' (RN) are excluded."""
    staff = StaffFactory.create()
    _make_lab_for(staff, review_mode=DocumentReviewMode.REVIEW_NOT_REQUIRED)
    _make_imaging_for(staff, review_mode=DocumentReviewMode.REVIEW_NOT_REQUIRED)

    rows = _data(_make_handler(str(staff.id)))
    assert rows == []


@pytest.mark.django_db
def test_get_data_includes_blank_review_mode() -> None:
    """A blank/unset review_mode still surfaces (fail toward visibility)."""
    staff = StaffFactory.create()
    _make_lab_for(staff, review_mode="")

    rows = _data(_make_handler(str(staff.id)))
    assert len(rows) == 1


@pytest.mark.django_db
def test_get_data_sorts_abnormal_first_then_oldest() -> None:
    """Abnormal results lead; within each group, oldest-pending comes first."""
    staff = StaffFactory.create()
    # Normal, very old.
    _make_lab_for(staff, test_name="Old Normal", days_ago=30, abnormal=False)
    # Abnormal, recent.
    _make_lab_for(staff, test_name="Recent Abnormal", days_ago=2, abnormal=True)
    # Abnormal, older.
    _make_lab_for(staff, test_name="Old Abnormal", days_ago=10, abnormal=True)

    rows = _data(_make_handler(str(staff.id)))
    order = [row["name"] for row in rows]
    assert order == ["Old Abnormal", "Recent Abnormal", "Old Normal"]


@pytest.mark.django_db
def test_get_data_imaging_never_abnormal() -> None:
    """Imaging rows never carry the abnormal flag (no structured flag exists)."""
    staff = StaffFactory.create()
    _make_imaging_for(staff)

    rows = _data(_make_handler(str(staff.id)))
    assert rows[0]["abnormal"] is False


@pytest.mark.django_db
def test_get_data_deduplicates_multi_test_lab_report() -> None:
    """A report with several matching tests appears once, not once per test."""
    staff = StaffFactory.create()
    report = LabReportFactory.create()
    order = LabOrderFactory.create(ordering_provider=staff)
    LabTestFactory.create(report=report, order=order, ontology_test_name="Sodium")
    LabTestFactory.create(report=report, order=order, ontology_test_name="Potassium")

    rows = _data(_make_handler(str(staff.id)))
    assert len(rows) == 1
    # Both test names are folded into the single row's display name.
    assert rows[0]["name"] == "Potassium, Sodium"


# ── Helper unit tests ──────────────────────────────────────────────────────


def test_days_pending_counts_whole_days() -> None:
    assert _days_pending(datetime.date(2026, 6, 5), TODAY) == 7


def test_days_pending_none_date_is_zero() -> None:
    assert _days_pending(None, TODAY) == 0


def test_days_pending_future_date_clamped_to_zero() -> None:
    assert _days_pending(datetime.date(2026, 6, 20), TODAY) == 0


def test_is_abnormal_true_when_any_value_flagged() -> None:
    report = MagicMock()
    v1, v2 = MagicMock(abnormal_flag=""), MagicMock(abnormal_flag="L")
    report.values.all.return_value = [v1, v2]
    assert _is_abnormal(report) is True


def test_is_abnormal_false_when_all_blank() -> None:
    report = MagicMock()
    report.values.all.return_value = [
        MagicMock(abnormal_flag=""),
        MagicMock(abnormal_flag="  "),
    ]
    assert _is_abnormal(report) is False


def test_lab_result_name_joins_distinct_sorted_tests() -> None:
    report = MagicMock()
    report.tests.all.return_value = [
        MagicMock(ontology_test_name="Sodium"),
        MagicMock(ontology_test_name="Sodium"),
        MagicMock(ontology_test_name="Glucose"),
    ]
    assert _lab_result_name(report) == "Glucose, Sodium"


def test_lab_result_name_falls_back_to_custom_document_name() -> None:
    report = MagicMock()
    report.tests.all.return_value = []
    report.custom_document_name = "Scanned report"
    assert _lab_result_name(report) == "Scanned report"


def test_lab_result_name_falls_back_to_generic_label() -> None:
    report = MagicMock()
    report.tests.all.return_value = [MagicMock(ontology_test_name="  ")]
    report.custom_document_name = ""
    assert _lab_result_name(report) == "Lab result"


def test_patient_name_handles_missing_patient() -> None:
    report = MagicMock()
    report.patient = None
    assert _patient_name(report) == "Unknown Patient"


def test_sort_key_orders_abnormal_dated_oldest_first() -> None:
    abnormal_old = {"abnormal": True, "result_date": "2026-06-01", "days_pending": 11}
    abnormal_new = {"abnormal": True, "result_date": "2026-06-10", "days_pending": 2}
    normal = {"abnormal": False, "result_date": "2026-05-01", "days_pending": 42}
    no_date = {"abnormal": False, "result_date": None, "days_pending": 0}

    rows: list[dict[str, Any]] = [normal, no_date, abnormal_new, abnormal_old]
    rows.sort(key=_sort_key)
    assert rows == [abnormal_old, abnormal_new, normal, no_date]
