"""Results Follow-Up Queue SimpleAPI handler.

Serves the HTML shell, static assets, and JSON data for the queue modal. The
``/data`` route returns the lab and imaging results awaiting review for the
logged-in provider (the ordering provider), flagged abnormal-first and
oldest-pending-first.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.common import DocumentReviewMode
from canvas_sdk.v1.data.imaging import ImagingReport
from canvas_sdk.v1.data.lab import LabReport

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class QueueAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the results follow-up queue modal UI and data.

    Routes:
        GET /          – HTML shell (index.html)
        GET /main.js   – JavaScript asset
        GET /styles.css – CSS asset
        GET /data      – JSON list of results awaiting the provider's review
    """

    PREFIX = "/app"

    # ── Static asset routes ───────────────────────────────────────────────

    @api.get("/")
    def get_index(self) -> list[Response | Effect]:
        """Serve the HTML shell for the modal."""
        html = render_to_string(
            "templates/index.html",
            context={"cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html or "", status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve the JavaScript asset."""
        return [
            Response(
                (render_to_string("static/main.js") or "").encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the CSS asset."""
        return [
            Response(
                (render_to_string("static/styles.css") or "").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    # ── Data route ────────────────────────────────────────────────────────

    @api.get("/data")
    def get_data(self) -> list[Response | Effect]:
        """Return the results awaiting review for the logged-in provider.

        Returns 400 if the staff UUID header is missing.
        """
        staff_uuid = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_uuid:
            return [
                JSONResponse(
                    {"error": "Missing canvas-logged-in-user-id header"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        today = datetime.now(timezone.utc).date()

        # Two bulk queries total — one for labs, one for imaging. No per-result
        # queries; abnormal detection and date math happen in Python over the
        # already-prefetched rows.
        lab_reports = (
            LabReport.objects.filter(
                tests__order__ordering_provider__id=staff_uuid,
                review__isnull=True,
                junked=False,
                deleted=False,
                entered_in_error__isnull=True,
            )
            .exclude(review_mode=DocumentReviewMode.REVIEW_NOT_REQUIRED)
            .select_related("patient")
            .prefetch_related("values", "tests")
            # A report joins to many tests, so the provider filter can duplicate
            # rows. Plain .distinct() collapses them. NOT .distinct("field") —
            # Postgres-only DISTINCT ON breaks the SQLite test harness.
            .distinct()
        )

        imaging_reports = (
            ImagingReport.objects.filter(
                order__ordering_provider__id=staff_uuid,
                review__isnull=True,
                junked=False,
            )
            .exclude(review_mode=DocumentReviewMode.REVIEW_NOT_REQUIRED)
            .select_related("patient", "order")
        )

        rows = [_lab_row(report, today) for report in lab_reports]
        rows += [_imaging_row(report, today) for report in imaging_reports]

        rows.sort(key=_sort_key)

        return [JSONResponse({"results": rows})]


# ── Helpers ───────────────────────────────────────────────────────────────


def _lab_row(report: LabReport, today: date) -> dict[str, Any]:
    """Assemble a result-row dict for a single lab report."""
    result_date = report.date_performed.date() if report.date_performed else None
    return {
        "patient_key": _patient_key(report),
        "patient_name": _patient_name(report),
        "type": "lab",
        "name": _lab_result_name(report),
        "result_date": result_date.isoformat() if result_date else None,
        "days_pending": _days_pending(result_date, today),
        "abnormal": _is_abnormal(report),
        "requires_signature": bool(report.requires_signature),
    }


def _imaging_row(report: ImagingReport, today: date) -> dict[str, Any]:
    """Assemble a result-row dict for a single imaging report.

    Imaging has no structured abnormal flag, so ``abnormal`` is always False.
    """
    result_date = report.result_date
    return {
        "patient_key": _patient_key(report),
        "patient_name": _patient_name(report),
        "type": "imaging",
        "name": report.name or "Imaging result",
        "result_date": result_date.isoformat() if result_date else None,
        "days_pending": _days_pending(result_date, today),
        "abnormal": False,
        "requires_signature": bool(report.requires_signature),
    }


def _patient_key(report: LabReport | ImagingReport) -> str:
    """Return the string patient key used for the companion chart deep-link.

    This is ``patient.id`` (the UUID string Canvas uses for
    ``/companion/patient/<key>``), NOT the integer ``dbid``.
    """
    patient = report.patient
    return str(patient.id) if patient else ""


def _patient_name(report: LabReport | ImagingReport) -> str:
    """Return the patient's display name, or a placeholder if unavailable."""
    patient = report.patient
    if not patient:
        return "Unknown Patient"
    name = f"{patient.first_name} {patient.last_name}".strip()
    return name or "Unknown Patient"


def _lab_result_name(report: LabReport) -> str:
    """Return a display name built from the report's test names.

    Deduplicates and joins the prefetched tests' ontology names; falls back to
    the custom document name, then a generic label.
    """
    names = sorted(
        {
            test.ontology_test_name.strip()
            for test in report.tests.all()
            if test.ontology_test_name.strip()
        }
    )
    if names:
        return ", ".join(names)
    return (report.custom_document_name or "").strip() or "Lab result"


def _is_abnormal(report: LabReport) -> bool:
    """Return True if any of the report's lab values carries an abnormal flag."""
    return any((value.abnormal_flag or "").strip() for value in report.values.all())


def _days_pending(result_date: date | None, today: date) -> int:
    """Return whole days between the result date and today.

    Unknown dates yield 0 (and sort last via :func:`_sort_key`). Future dates
    are clamped to 0 rather than reported as negative.
    """
    if result_date is None:
        return 0
    return max((today - result_date).days, 0)


def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
    """Sort abnormal results first, then oldest-pending first.

    Rows with no result date sort last within their abnormal/normal group.
    """
    abnormal_rank = 0 if row["abnormal"] else 1
    no_date_rank = 0 if row["result_date"] is not None else 1
    # Negate so the longest wait (largest days_pending) comes first.
    return (abnormal_rank, no_date_rank, -row["days_pending"])
