from __future__ import annotations

from typing import Any

from logger import log

from canvas_sdk.v1.data.lab import LabReport, LabReview, LabTest, LabValue

from chart_command_search.searchers.constants import MAX_RESULTS
from chart_command_search.searchers.helpers import (
    detail,
    fmt_date,
    make_result,
    parse_multi,
)
from chart_command_search.searchers.types import Result


def search_labs(
    patient_id: str,
    q: str,
    status: str,
    date_from: str = "",
    date_to: str = "",
    provider_id: str = "",
) -> list[Result]:
    qs = LabReport.objects.filter(patient__id=patient_id, junked=False)
    if date_from:
        qs = qs.filter(date_performed__date__gte=date_from)
    if date_to:
        qs = qs.filter(date_performed__date__lte=date_to)
    qs = qs.order_by("-date_performed")[:MAX_RESULTS]
    reports = list(qs)
    if not reports:
        return []

    report_dbids = [r.dbid for r in reports]

    reviews_map: dict[int, Any] = {}
    try:
        for rev in LabReview.objects.filter(lab_report__dbid__in=report_dbids):
            reviews_map[rev.lab_report_id] = rev
    except Exception as exc:
        log.error("Failed to fetch lab reviews: %s", exc)

    tests_map: dict[int, list[Any]] = {}
    try:
        for t in LabTest.objects.filter(
            lab_report__dbid__in=report_dbids
        ).select_related("lab_order"):
            tests_map.setdefault(t.lab_report_id, []).append(t)
    except Exception as exc:
        log.error("Failed to fetch lab tests: %s", exc)

    test_dbids: list[int] = []
    for tlist in tests_map.values():
        test_dbids.extend(t.dbid for t in tlist)
    values_map: dict[int, list[Any]] = {}
    if test_dbids:
        try:
            for v in LabValue.objects.filter(lab_test__dbid__in=test_dbids):
                values_map.setdefault(v.lab_test_id, []).append(v)
        except Exception as exc:
            log.error("Failed to fetch lab values: %s", exc)

    if q:
        q_lower = q.lower()
        matching_dbids: set[int] = set()
        for r in reports:
            doc_name = (getattr(r, "custom_document_name", "") or "").lower()
            req_num = (getattr(r, "requisition_number", "") or "").lower()
            if q_lower in doc_name or q_lower in req_num:
                matching_dbids.add(r.dbid)
        for report_dbid, tlist in tests_map.items():
            for t in tlist:
                test_name = (getattr(t, "ontology_test_name", "") or "").lower()
                if q_lower in test_name:
                    matching_dbids.add(report_dbid)
        reports = [r for r in reports if r.dbid in matching_dbids]

    provider_ids = parse_multi(provider_id)
    if provider_ids:
        provider_report_dbids: set[int] = set()
        for report_dbid, tlist in tests_map.items():
            for t in tlist:
                order = getattr(t, "lab_order", None)
                if order:
                    prov = getattr(order, "ordering_provider_id", None)
                    if prov and str(prov) in provider_ids:
                        provider_report_dbids.add(report_dbid)
        reports = [r for r in reports if r.dbid in provider_report_dbids]

    statuses = parse_multi(status)

    results: list[Result] = []
    for report in reports:
        tests = tests_map.get(report.dbid, [])
        review = reviews_map.get(report.dbid)
        test_names = [
            getattr(t, "ontology_test_name", "") or "" for t in tests
        ]
        test_names = [n for n in test_names if n]

        has_abnormal = False
        for t in tests:
            for v in values_map.get(t.dbid, []):
                if getattr(v, "abnormal_flag", ""):
                    has_abnormal = True
                    break
            if has_abnormal:
                break

        test_statuses = {getattr(t, "status", "") for t in tests}
        has_failed = bool(test_statuses & {"SF", "PF"})
        has_received = "RE" in test_statuses
        tx_type = (getattr(report, "transmission_type", "") or "").strip()

        review_status = (getattr(review, "status", "") or "").lower() if review else ""
        if review_status == "completed":
            state = "Reviewed"
            state_class = "completed"
            filter_key = "reviewed"
        elif has_abnormal:
            state = "Abnormal"
            state_class = "cancelled"
            filter_key = "results_in"
        elif has_received:
            state = "Results In"
            state_class = "active"
            filter_key = "results_in"
        elif has_failed:
            state = "Error"
            state_class = "cancelled"
            filter_key = "error"
        elif tx_type == "F":
            state = "Faxed"
            state_class = "completed"
            filter_key = "ordered"
        elif "PR" in test_statuses:
            state = "Ordered"
            state_class = "active"
            filter_key = "ordered"
        elif "SE" in test_statuses:
            state = "Processing"
            state_class = "pending"
            filter_key = "ordered"
        elif "SR" in test_statuses:
            state = "Saved"
            state_class = "uncommitted"
            filter_key = "open"
        else:
            state = "Open"
            state_class = "uncommitted"
            filter_key = "open"

        if statuses and filter_key not in statuses:
            continue

        doc_name = (getattr(report, "custom_document_name", "") or "").strip()
        summary = doc_name if doc_name else ", ".join(test_names)

        details: list[dict[str, str]] = []
        if test_names and doc_name:
            details.append(detail("Tests", ", ".join(test_names)))
        date_performed = getattr(report, "date_performed", None)
        if date_performed:
            details.append(detail("Date Performed", fmt_date(date_performed)))
        req_num = (getattr(report, "requisition_number", "") or "").strip()
        if req_num:
            details.append(detail("Requisition #", req_num))
        tx_type = (getattr(report, "transmission_type", "") or "").strip()
        if tx_type:
            details.append(detail("Transmission", tx_type))

        results.append(
            make_result(
                category="lab",
                type_label="Lab Report",
                summary=summary,
                details=details,
                state=state,
                state_class=state_class,
                permalink="",
                date=fmt_date(date_performed),
            )
        )
    return results
