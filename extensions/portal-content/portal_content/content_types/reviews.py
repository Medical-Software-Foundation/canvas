"""Review-gating for lab and imaging results.

When HOLD_UNREVIEWED_RESULTS is enabled, the portal hides only the results that
are *waiting on* a provider review - i.e. the result requires review
(``review_mode == "RR"``) but none has happened yet. Results that do not require
review (``review_mode == "RN"``) and results that have already been reviewed are
shown as normal.

"Requires review" / "reviewed" live on the SDK LabReport / ImagingReport, not in
the FHIR documents, so this maps each FHIR document back to its SDK report:

- Labs: FHIR doc -> DiagnosticReport id -> DiagnosticReport.lab (precise).
- Imaging: there is no SDK link from the FHIR imaging document to the
  ImagingReport, so a result is hidden conservatively by matching its date to an
  imaging report that is itself waiting on review.
"""

from __future__ import annotations

from canvas_sdk.v1.data.diagnostic_report import DiagnosticReport
from canvas_sdk.v1.data.imaging import ImagingReport

# LabReport / ImagingReport.review_mode value meaning a provider review is required.
REVIEW_REQUIRED = "RR"


def filter_reviewed(reports: list[dict], component: str, patient_id: str) -> list[dict]:
    """Drop results that are waiting on a provider review; keep everything else."""
    if component == "labs":
        return _drop_pending_labs(reports)
    if component == "imaging":
        return _drop_pending_imaging(reports, patient_id)
    return reports


def _drop_pending_labs(reports: list[dict]) -> list[dict]:
    dr_ids = [r["diagnostic_report_id"] for r in reports if r.get("diagnostic_report_id")]
    pending = {
        str(dr.id)
        for dr in DiagnosticReport.objects.filter(id__in=dr_ids).select_related("lab")
        if dr.lab and dr.lab.review_mode == REVIEW_REQUIRED and not dr.lab.review_id
    }
    return [r for r in reports if r.get("diagnostic_report_id") not in pending]


def _drop_pending_imaging(reports: list[dict], patient_id: str) -> list[dict]:
    pending_dates = {
        report.result_date.isoformat()
        for report in ImagingReport.objects.filter(
            patient__id=patient_id, review_mode=REVIEW_REQUIRED, review__isnull=True, junked=False
        )
        if report.result_date
    }
    return [r for r in reports if (r.get("date") or "")[:10] not in pending_dates]
