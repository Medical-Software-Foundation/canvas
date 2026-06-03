from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from chart_command_search.searchers.labs import search_labs


def _mock_obj(**kwargs: Any) -> MagicMock:
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_report(**overrides: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "dbid": 10,
        "custom_document_name": "CBC Panel",
        "requisition_number": "REQ-001",
        "date_performed": datetime(2024, 3, 1),
        "transmission_type": "",
    }
    defaults.update(overrides)
    return _mock_obj(**defaults)


def _setup_lab_qs(
    mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any,
    reports: list[Any], reviews: list[Any] | None = None,
    tests: list[Any] | None = None, values: list[Any] | None = None,
) -> None:
    qs = mock_report.objects.filter.return_value
    qs.filter.return_value = qs
    qs.order_by.return_value.__getitem__ = lambda self, s: reports
    mock_review.objects.filter.return_value = reviews or []
    mock_test.objects.filter.return_value.select_related.return_value = tests or []
    mock_value.objects.filter.return_value = values or []


@patch("chart_command_search.searchers.labs.LabValue")
@patch("chart_command_search.searchers.labs.LabTest")
@patch("chart_command_search.searchers.labs.LabReview")
@patch("chart_command_search.searchers.labs.LabReport")
class TestSearchLabsExtended:
    def test_date_filters(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report])
        results = search_labs("p1", "", "", date_from="2024-01-01", date_to="2024-12-31")
        assert len(results) == 1

    def test_provider_filter(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(
            dbid=20, lab_report_id=10, ontology_test_name="CBC", status="RE",
            lab_order=_mock_obj(ordering_provider_id="prov-1"),
        )
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "", provider_id="prov-1")
        assert len(results) == 1

    def test_provider_filter_no_match(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(
            dbid=20, lab_report_id=10, ontology_test_name="CBC", status="RE",
            lab_order=_mock_obj(ordering_provider_id="prov-1"),
        )
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "", provider_id="prov-999")
        assert len(results) == 0

    def test_text_search_by_test_name(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report(custom_document_name="")
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="Glucose", status="RE", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "Glucose", "")
        assert len(results) == 1

    def test_text_search_by_requisition(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report(requisition_number="REQ-123")
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report])
        results = search_labs("p1", "REQ-123", "")
        assert len(results) == 1

    def test_status_results_in(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="CBC", status="RE", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "results_in")
        assert len(results) == 1
        assert results[0]["state"] == "Results In"

    def test_status_error(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="CBC", status="SF", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "")
        assert results[0]["state"] == "Error"

    def test_status_faxed(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report(transmission_type="F")
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report])
        results = search_labs("p1", "", "")
        assert results[0]["state"] == "Faxed"

    def test_status_ordered(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="CBC", status="PR", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "")
        assert results[0]["state"] == "Ordered"

    def test_status_processing(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="CBC", status="SE", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "")
        assert results[0]["state"] == "Processing"

    def test_status_saved(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="CBC", status="SR", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test_obj])
        results = search_labs("p1", "", "")
        assert results[0]["state"] == "Saved"

    def test_status_open_default(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report])
        results = search_labs("p1", "", "")
        assert results[0]["state"] == "Open"

    def test_review_fetch_exception(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        qs = mock_report.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report]
        mock_review.objects.filter.side_effect = RuntimeError("db error")
        mock_test.objects.filter.return_value.select_related.return_value = []
        mock_value.objects.filter.return_value = []

        results = search_labs("p1", "", "")
        assert len(results) == 1

    def test_test_fetch_exception(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        qs = mock_report.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report]
        mock_review.objects.filter.return_value = []
        mock_test.objects.filter.side_effect = RuntimeError("db error")
        mock_value.objects.filter.return_value = []

        results = search_labs("p1", "", "")
        assert len(results) == 1

    def test_value_fetch_exception(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report()
        test_obj = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="CBC", status="RE", lab_order=None)
        qs = mock_report.objects.filter.return_value
        qs.filter.return_value = qs
        qs.order_by.return_value.__getitem__ = lambda self, s: [report]
        mock_review.objects.filter.return_value = []
        mock_test.objects.filter.return_value.select_related.return_value = [test_obj]
        mock_value.objects.filter.side_effect = RuntimeError("db error")

        results = search_labs("p1", "", "")
        assert len(results) == 1

    def test_summary_falls_back_to_test_names(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report(custom_document_name="")
        test1 = _mock_obj(dbid=20, lab_report_id=10, ontology_test_name="Glucose", status="RE", lab_order=None)
        test2 = _mock_obj(dbid=21, lab_report_id=10, ontology_test_name="HbA1c", status="RE", lab_order=None)
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report], tests=[test1, test2])
        results = search_labs("p1", "", "")
        assert results[0]["summary"] == "Glucose, HbA1c"

    def test_details_include_transmission(
        self, mock_report: Any, mock_review: Any, mock_test: Any, mock_value: Any
    ) -> None:
        report = _make_report(transmission_type="HL7")
        _setup_lab_qs(mock_report, mock_review, mock_test, mock_value, [report])
        results = search_labs("p1", "", "")
        tx_details = [d for d in results[0]["details"] if d["label"] == "Transmission"]
        assert tx_details[0]["value"] == "HL7"
