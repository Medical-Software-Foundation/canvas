"""ExamSearchAPI — database-backed search endpoints powering the form's
dropdowns.

Routes (Checkpoint 2):
  - GET /exam/search/rfv-codings?q=...&limit=...

Future checkpoints add /exam/search/icd10, /exam/search/labs, etc. per
spec §6.

Auth: StaffSessionAuthMixin — staff session only, no API-key fallback.
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.utils.http import ontologies_http
from exam_chart_app.data.db_safety import swallow_db_read
from exam_chart_app.data.imaging_codes import get_imaging_codes
from canvas_sdk.v1.data import (
    LabPartner,
    LabPartnerTest,
    ReasonForVisitSettingCoding,
    ServiceProvider,
    Staff,
)
from django.db.models import Q
from logger import log

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def _parse_limit(raw: str) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if n < 1:
        return DEFAULT_LIMIT
    return min(n, MAX_LIMIT)


class ExamSearchAPI(StaffSessionAuthMixin, SimpleAPI):
    """Search endpoints for the Exam tab dropdowns."""

    # See ExamChartingAPI for the PREFIX rationale — same SDK requirement.
    PREFIX = ""

    @api.get("/exam/search/rfv-codings")
    def search_rfv_codings(self) -> list[Response | Effect]:
        query = (self.request.query_params.get("q") or "").strip()
        limit = _parse_limit(self.request.query_params.get("limit") or "")

        if not query:
            return [JSONResponse({"results": []}, status_code=HTTPStatus.OK)]

        rows = swallow_db_read(
            f"/exam/search/rfv-codings ReasonForVisitSettingCoding.filter(q={query!r})",
            lambda: list(
                ReasonForVisitSettingCoding.objects
                .filter(Q(display__icontains=query) | Q(code__iexact=query))
                .distinct()
                .order_by("display")
                [:limit]
            ),
            default=[],
        )
        results = [
            {"code": r.code or "", "system": r.system or "", "display": r.display or ""}
            for r in rows
        ]
        return [JSONResponse({"results": results}, status_code=HTTPStatus.OK)]

    @api.get("/exam/search/lab-partners")
    def search_lab_partners(self) -> list[Response | Effect]:
        query = (self.request.query_params.get("q") or "").strip()
        limit = _parse_limit(self.request.query_params.get("limit") or "")
        qs_filter: dict[str, Any] = {"active": True}
        if query:
            qs_filter["name__icontains"] = query
        rows = swallow_db_read(
            f"/exam/search/lab-partners LabPartner.filter(q={query!r})",
            lambda: list(
                LabPartner.objects.filter(**qs_filter).order_by("name")[:limit]
            ),
            default=[],
        )
        return [JSONResponse({
            "results": [{"id": str(r.id), "name": r.name or ""} for r in rows]
        }, status_code=HTTPStatus.OK)]

    @api.get("/exam/search/lab-tests")
    def search_lab_tests(self) -> list[Response | Effect]:
        partner_id = (self.request.query_params.get("partner_id") or "").strip()
        if not partner_id:
            return [JSONResponse({"results": []}, status_code=HTTPStatus.OK)]
        query = (self.request.query_params.get("q") or "").strip()
        limit = _parse_limit(self.request.query_params.get("limit") or "")
        qs_filter: dict[str, Any] = {"lab_partner__id": partner_id}
        if query:
            qs_filter["order_name__icontains"] = query
        rows = swallow_db_read(
            f"/exam/search/lab-tests LabPartnerTest.filter(partner_id={partner_id!r}, q={query!r})",
            lambda: list(
                LabPartnerTest.objects.filter(**qs_filter).order_by("order_name")[:limit]
            ),
            default=[],
        )
        return [JSONResponse({
            "results": [
                {"order_code": r.order_code or "", "order_name": r.order_name or ""}
                for r in rows
            ]
        }, status_code=HTTPStatus.OK)]

    @api.get("/exam/search/medications")
    def search_medications(self) -> list[Response | Effect]:
        """Search FDB grouped-medication compendium via Canvas Ontologies.

        Backed by `ontologies_http.get_json("/fdb/grouped-medication/?...")`,
        which returns proper FDB GCN codes (`med_medication_id`) plus the
        NDC + NCPDP qualifier needed to build a `ClinicalQuantity` for
        `PrescribeCommand.type_to_dispense`. This is the same data source
        Canvas's own Prescribe UI pulls from.

        Response shape per result:
          {
            fdb_code: str,
            display: str,
            description_and_quantity: str,
            rxnorm_rxcui: str,
            clinical_quantities: [
              {representative_ndc, ncpdp_quantity_qualifier_code,
               quantity_description, erx_quantity}
            ],
          }
        """
        query = (self.request.query_params.get("q") or "").strip()
        limit = _parse_limit(self.request.query_params.get("limit") or "")
        if not query or len(query) < 2:
            return [JSONResponse({"results": []}, status_code=HTTPStatus.OK)]
        try:
            response = ontologies_http.get_json(
                f"/fdb/grouped-medication/?{urlencode({'search': query})}"
            )
            data = response.json()
        except (OSError, ValueError):
            # Narrow to network + decode errors so AttributeError /
            # KeyError / TypeError from programming bugs (renamed SDK
            # attrs, wrong response shape) reach Sentry rather than
            # silently degrade. The catch list intentionally uses
            # builtins rather than ``requests.exceptions.RequestException``
            # — Canvas's plugin sandbox blocks ``requests.exceptions`` at
            # the import allowlist, so referencing it at module top
            # raises ImportError on plugin load. ``RequestException``
            # inherits from ``IOError`` (which is the ``OSError`` alias
            # in Python 3), so ``OSError`` catches every real network
            # failure the SDK can raise from this call. ``ValueError`` is
            # the parent of ``JSONDecodeError`` and covers the malformed
            # JSON-body case. Expected failures degrade to empty results
            # so the UI stays usable; log.exception pages on-call.
            log.exception(
                "[ExamSearchAPI] ontologies_http /fdb/grouped-medication failed"
            )
            return [JSONResponse({"results": []}, status_code=HTTPStatus.OK)]
        raw_results = data.get("results", []) if isinstance(data, dict) else []
        results: list[dict[str, Any]] = []
        for med in raw_results[:limit]:
            if not isinstance(med, dict):
                continue
            clinical_quantities_raw = med.get("clinical_quantities") or []
            clinical_quantities = [
                {
                    "representative_ndc": cq.get("representative_ndc", "") or "",
                    "ncpdp_quantity_qualifier_code":
                        cq.get("erx_ncpdp_script_quantity_qualifier_code", "") or "",
                    "quantity_description":
                        cq.get("clinical_quantity_description", "") or "",
                    "erx_quantity": cq.get("erx_quantity", "") or "",
                }
                for cq in clinical_quantities_raw
                if isinstance(cq, dict)
            ]
            results.append({
                "fdb_code": str(med.get("med_medication_id", "") or ""),
                "display": med.get("med_medication_description", "") or "",
                "description_and_quantity":
                    med.get("description_and_quantity", "") or "",
                "rxnorm_rxcui": str(med.get("rxnorm_rxcui", "") or ""),
                "clinical_quantities": clinical_quantities,
            })
        return [JSONResponse({"results": results}, status_code=HTTPStatus.OK)]

    @api.get("/exam/search/imaging-codes")
    def search_imaging_codes(self) -> list[Response | Effect]:
        """Return the imaging-codes picklist (CPT-coded studies).

        Sources from the `exam-imaging-codes` plugin secret when set —
        admin pastes verbatim entries from the chart's CPT typeahead so
        each label matches the instance's catalog character-for-character.
        Falls back to the bundled defaults when unset.
        """
        secret_value = self.secrets.get("exam-imaging-codes") or ""
        return [JSONResponse(
            {"results": get_imaging_codes(secret_value)},
            status_code=HTTPStatus.OK,
        )]

    @api.get("/exam/search/service-providers")
    def search_service_providers(self) -> list[Response | Effect]:
        """List specialists for the Refer card's dropdown.

        Empty query returns all ServiceProvider rows (bounded by limit) so
        the frontend can preload a <select> at tab-load. Non-empty query
        filters by first_name / last_name / practice_name (icontains).
        Mirrors the LabPartner preload pattern.
        """
        query = (self.request.query_params.get("q") or "").strip()
        limit = _parse_limit(self.request.query_params.get("limit") or "")

        def _fetch_service_providers() -> list:
            qs = ServiceProvider.objects.all()
            if query:
                qs = qs.filter(
                    Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                    | Q(practice_name__icontains=query)
                )
            return list(qs.order_by("last_name", "first_name")[:limit])

        rows = swallow_db_read(
            f"/exam/search/service-providers ServiceProvider.filter(q={query!r})",
            _fetch_service_providers,
            default=[],
        )
        return [JSONResponse({
            "results": [
                {
                    "id": str(r.id),
                    "first_name": r.first_name or "",
                    "last_name": r.last_name or "",
                    "specialty": r.specialty or "",
                    "practice_name": r.practice_name or "",
                }
                for r in rows
            ]
        }, status_code=HTTPStatus.OK)]

    @api.get("/exam/search/staff")
    def search_staff(self) -> list[Response | Effect]:
        """List active Staff who hold a PROVIDER StaffRole.

        Imaging / Lab / Rx ordering-provider fields are bound, chart-side,
        to staff with `role_type='PROVIDER'`. Non-provider system users
        (admin / scheduler / billing) get silently dropped when the chart
        tries to resolve `ordering_provider_key` → display name. Filtering
        at the source keeps the dropdown free of staff who'd render blank
        on the resulting command.
        """
        query = (self.request.query_params.get("q") or "").strip()
        limit = _parse_limit(self.request.query_params.get("limit") or "")

        def _fetch_staff() -> list:
            qs = (
                Staff.objects
                .filter(active=True, roles__role_type="PROVIDER")
                .distinct()
            )
            if query:
                qs = qs.filter(
                    Q(first_name__icontains=query) | Q(last_name__icontains=query)
                )
            return list(qs.order_by("last_name", "first_name")[:limit])

        rows = swallow_db_read(
            f"/exam/search/staff Staff.filter(q={query!r})",
            _fetch_staff,
            default=[],
        )
        return [JSONResponse({
            "results": [
                {
                    "id": str(r.id),
                    "first_name": r.first_name or "",
                    "last_name": r.last_name or "",
                    "npi_number": r.npi_number or "",
                }
                for r in rows
            ]
        }, status_code=HTTPStatus.OK)]
