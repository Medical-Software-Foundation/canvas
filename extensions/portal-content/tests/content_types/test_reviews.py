"""Tests for review-gating of lab/imaging results.

Gating hides only results *waiting on* a provider review: review required
(review_mode == "RR") and not yet reviewed. Results that don't require review
(review_mode == "RN") and reviewed results are kept.
"""

from datetime import date
from unittest.mock import MagicMock, patch

from portal_content.content_types import reviews


def _dr(dr_id, review_mode, reviewed):
    dr = MagicMock(id=dr_id)
    dr.lab = MagicMock(review_mode=review_mode, review_id=99 if reviewed else None)
    return dr


@patch("portal_content.content_types.reviews.DiagnosticReport")
def test_labs_hides_only_pending_review(dr_model):
    reports = [
        {"report_id": "a", "diagnostic_report_id": "dr1"},  # RR, unreviewed -> hidden
        {"report_id": "b", "diagnostic_report_id": "dr2"},  # RR, reviewed   -> shown
        {"report_id": "c", "diagnostic_report_id": "dr3"},  # RN             -> shown
        {"report_id": "d", "diagnostic_report_id": None},   # no DR link     -> shown
    ]
    dr_model.objects.filter.return_value.select_related.return_value = [
        _dr("dr1", "RR", reviewed=False),
        _dr("dr2", "RR", reviewed=True),
        _dr("dr3", "RN", reviewed=False),
    ]
    out = reviews.filter_reviewed(reports, "labs", "patient-1")
    assert [r["report_id"] for r in out] == ["b", "c", "d"]


@patch("portal_content.content_types.reviews.DiagnosticReport")
def test_labs_imaging_dr_without_lab_is_shown(dr_model):
    # an imaging DiagnosticReport has lab=None -> never counts as pending lab
    dr = MagicMock(id="dr1")
    dr.lab = None
    dr_model.objects.filter.return_value.select_related.return_value = [dr]
    out = reviews.filter_reviewed([{"report_id": "a", "diagnostic_report_id": "dr1"}], "labs", "p")
    assert [r["report_id"] for r in out] == ["a"]


@patch("portal_content.content_types.reviews.ImagingReport")
def test_imaging_hides_dates_pending_review(img_model):
    pending = MagicMock(result_date=date(2026, 1, 10))
    img_model.objects.filter.return_value = [pending]
    reports = [
        {"report_id": "x", "date": "2026-01-10T08:00:00Z"},  # matches pending date -> hidden
        {"report_id": "y", "date": "2026-02-01T00:00:00Z"},  # no pending review    -> shown
    ]
    out = reviews.filter_reviewed(reports, "imaging", "patient-1")
    assert [r["report_id"] for r in out] == ["y"]
    # the ImagingReport queryset filters on the patient + a required-but-unreviewed result
    _, kwargs = img_model.objects.filter.call_args
    assert kwargs == {
        "patient__id": "patient-1",
        "review_mode": "RR",
        "review__isnull": True,
        "junked": False,
    }


def test_filter_reviewed_passthrough_for_non_result_components():
    reports = [{"report_id": "l"}]
    assert reviews.filter_reviewed(reports, "letters", "p") == reports
