"""Lookups the builder's command forms search.

These proxy
Canvas's ontology, science, and pharmacy services plus local lab-partner, staff,
and team records. An upstream failure returns an empty list flagged
``degraded`` rather than an error status, so one unreachable service leaves a
single search empty instead of breaking the form.
"""

from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.utils.http import ontologies_http, pharmacy_http, science_http
from canvas_sdk.v1.data.dme import DmeProduct
from canvas_sdk.v1.data.lab import LabPartner
from canvas_sdk.v1.data.practicelocation import PracticeLocationSetting
from canvas_sdk.v1.data.service_provider import ServiceProvider
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.team import Team
from django.db.models import Q
from logger import log

from charting_tools.command_forms import dme_product_ref
from charting_tools.settings import staff_can_manage_templates
from charting_tools.umls import UmlsError, api_key, search_icd10

RESULT_LIMIT = 50


def _ok(results: list[dict[str, Any]]) -> list[Response | Effect]:
    return [JSONResponse({"results": results}, status_code=HTTPStatus.OK)]


# What the Canvas lookup clients raise when the service is down or answers with
# something that isn't JSON: requests' errors are OSErrors, and a bad JSON body
# is a ValueError. Anything else is a bug and is left to raise.
UPSTREAM_ERRORS = (OSError, ValueError)


# Home-app's practice location setting for the zip codes it serves.
SERVICE_AREA_ZIP_CODES = "serviceAreaZipCodes"


# What a directory search matches on, and the columns a contact row is built from.
DIRECTORY_FIELDS = ("last_name", "first_name", "practice_name", "specialty")
DIRECTORY_COLUMNS = (
    *DIRECTORY_FIELDS,
    "business_phone",
    "business_fax",
    "business_address",
    "science_contact_id",
)


def _contact_row(row: dict[str, Any], source: str) -> dict[str, Any]:
    """A send-to contact as the forms store it, from Science or the directory."""
    first = row.get("firstName", row.get("first_name", "")) or ""
    last = row.get("lastName", row.get("last_name", "")) or ""
    practice = row.get("practiceName", row.get("practice_name", "")) or ""
    specialty = row.get("specialty", "") or ""
    name = " ".join(p for p in (first, last) if p) or practice
    return {
        "first_name": first,
        "last_name": last,
        "practice_name": practice,
        "specialty": specialty,
        "business_phone": row.get("businessPhone", row.get("business_phone", "")) or "",
        "business_fax": row.get("businessFax", row.get("business_fax", "")) or "",
        "business_address": row.get("businessAddress", row.get("business_address", "")) or "",
        "display": " - ".join(p for p in (name, specialty) if p),
        "source": source,
    }


def directory_providers(query: str) -> list[dict[str, Any]]:
    """Active customer-managed service providers matching by name, practice, or specialty."""
    matching = Q()
    for field in DIRECTORY_FIELDS:
        matching |= Q(**{f"{field}__icontains": query})
    providers = (
        ServiceProvider.objects.filter(matching, is_active=True, is_customer_managed=True)
        .order_by("last_name", "first_name")
        .values(*DIRECTORY_COLUMNS)[:RESULT_LIMIT]
    )
    rows: list[dict[str, Any]] = []
    for provider in providers:
        row = _contact_row(provider, "directory")
        row["science_contact_id"] = provider["science_contact_id"]
        rows.append(row)
    return rows


def _degraded(kind: str, error: Exception) -> list[Response | Effect]:
    log.warning(f"{kind} search failed: {error.__class__.__name__}")
    return [JSONResponse({"results": [], "degraded": True}, status_code=HTTPStatus.OK)]


class SearchAPI(StaffSessionAuthMixin, SimpleAPI):
    """Ontology, directory, and catalog lookups for the builder's forms."""

    PREFIX = "/search"

    def _query(self) -> str:
        return str(self.request.query_params.get("q") or "").strip()

    def _forbidden(self) -> list[Response | Effect] | None:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if staff_can_manage_templates(str(staff_id) if staff_id else None, self.secrets):
            return None
        return [JSONResponse({"error": "Forbidden"}, status_code=HTTPStatus.FORBIDDEN)]

    @api.get("/umls-icd10")
    def umls_icd10(self) -> list[Response | Effect]:
        """ICD-10-CM codes from UMLS, for a quickpick's or order set's diagnoses.

        Reports a failure instead of going quietly empty: a missing or rejected
        UMLS key is something the admin has to fix.
        """
        denied = self._forbidden()
        if denied:
            return denied
        try:
            results = search_icd10(self._query(), api_key(self.secrets))
        except UmlsError as error:
            return [JSONResponse({"error": str(error)}, status_code=HTTPStatus.BAD_GATEWAY)]
        return _ok(results)

    @api.get("/instruction")
    def instruction(self) -> list[Response | Effect]:
        """SNOMED instructions."""
        denied = self._forbidden()
        if denied:
            return denied
        query = self._query()
        if not query:
            return _ok([])
        try:
            payload = ontologies_http.get_json(
                f"/snomed/instruction/?{urlencode({'term__icontains': query})}"
            ).json()
        except UPSTREAM_ERRORS as error:
            return _degraded("instruction", error)
        return _ok(
            [
                {
                    "concept_id": str(row.get("concept_id") or row.get("snomed_concept_id")),
                    "display": row.get("term") or row.get("preferred_term", ""),
                }
                for row in payload.get("results", [])
                if row.get("concept_id") or row.get("snomed_concept_id")
            ][:RESULT_LIMIT]
        )

    @api.get("/imaging")
    def imaging(self) -> list[Response | Effect]:
        """Imaging studies from Canvas Science, the catalog ``image_code`` is drawn from."""
        denied = self._forbidden()
        if denied:
            return denied
        query = self._query()
        if not query:
            return _ok([])
        try:
            payload = science_http.get_json(
                "/parse-templates/imaging-reports"
                f"?{urlencode({'query': query, 'format': 'json', 'limit': RESULT_LIMIT})}"
            ).json()
        except UPSTREAM_ERRORS as error:
            return _degraded("imaging", error)
        return _ok(
            [
                {"code": str(row["code"]), "display": row.get("name", "")}
                for row in payload.get("results", [])
                if row.get("code")
            ][:RESULT_LIMIT]
        )

    @api.get("/contact")
    def contact(self) -> list[Response | Effect]:
        """Who a referral, imaging order, or DME order is sent to.

        The instance's own directory first (its active customer-managed service
        providers), then Canvas Science contacts the way home-app searches them:
        limited to the staff member's practice location service-area zip codes,
        and to radiology for imaging orders. A Science contact already in the
        directory isn't listed twice.
        """
        denied = self._forbidden()
        if denied:
            return denied
        query = self._query()
        if not query:
            return _ok([])
        directory = directory_providers(query)
        known = {row.pop("science_contact_id") for row in directory} - {None}
        params: dict[str, str] = {"search": query, "format": "json"}
        zip_codes = self._service_area_zip_codes()
        if zip_codes:
            params["business_postal_code__in"] = ",".join(zip_codes)
        if str(self.request.query_params.get("for") or "") == "imaging":
            params["job_title__icontains"] = "radiology"
        try:
            payload = science_http.get_json(f"/contacts/?{urlencode(params)}").json()
        except UPSTREAM_ERRORS as error:
            if directory:
                return _ok(directory[:RESULT_LIMIT])
            return _degraded("contact", error)
        science = [
            _contact_row(row, "science")
            for row in payload.get("results", [])
            if row.get("id") not in known
        ]
        return _ok((directory + science)[:RESULT_LIMIT])

    def _service_area_zip_codes(self) -> list[str]:
        """The service-area zip codes of the staff member's primary practice location."""
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        location_id = (
            Staff.objects.filter(id=staff_id).values_list("primary_practice_location_id", flat=True).first()
            if staff_id
            else None
        )
        if not location_id:
            return []
        value = (
            PracticeLocationSetting.objects.filter(practice_location_id=location_id, name=SERVICE_AREA_ZIP_CODES)
            .values_list("value", flat=True)
            .first()
        )
        return [str(z).strip() for z in value or [] if str(z).strip()] if isinstance(value, list) else []

    @api.get("/medication")
    def medication(self) -> list[Response | Effect]:
        """FDB medications with their dispensable quantities."""
        denied = self._forbidden()
        if denied:
            return denied
        query = self._query()
        if len(query) < 2:
            return _ok([])
        try:
            payload = ontologies_http.get_json(
                f"/fdb/grouped-medication/?{urlencode({'search': query})}"
            ).json()
        except UPSTREAM_ERRORS as error:
            return _degraded("medication", error)
        results = []
        for row in payload.get("results", [])[:RESULT_LIMIT]:
            fdb_code = row.get("med_medication_id")
            if not fdb_code:
                continue
            results.append(
                {
                    "fdb_code": str(fdb_code),
                    "display": row.get("description_and_quantity")
                    or row.get("med_medication_description", ""),
                    "clinical_quantities": [
                        {
                            "representative_ndc": q.get("representative_ndc", ""),
                            "ncpdp_quantity_qualifier_code": q.get(
                                "erx_ncpdp_script_quantity_qualifier_code", ""
                            ),
                            "display": q.get("clinical_quantity_description", ""),
                        }
                        for q in row.get("clinical_quantities") or []
                    ],
                }
            )
        return _ok(results)

    @api.get("/pharmacy")
    def pharmacy(self) -> list[Response | Effect]:
        """Pharmacies by name or address."""
        denied = self._forbidden()
        if denied:
            return denied
        query = self._query()
        if len(query) < 2:
            return _ok([])
        try:
            rows = pharmacy_http.search_pharmacies(query) or []
        except UPSTREAM_ERRORS as error:
            return _degraded("pharmacy", error)
        results = []
        for row in rows[:25]:
            ncpdp = row.get("ncpdp_id", "")
            if not ncpdp:
                continue
            name = row.get("organization_name", "")
            address = ", ".join(
                p for p in (row.get("address_line_1", ""), row.get("city", ""), row.get("state", "")) if p
            )
            results.append(
                {
                    "ncpdp_id": str(ncpdp),
                    "display": " - ".join(p for p in (name, address) if p) or str(ncpdp),
                }
            )
        return _ok(results)

    @api.get("/dme-products")
    def dme_products(self) -> list[Response | Effect]:
        """Active DME products on the formulary, by name or code."""
        denied = self._forbidden()
        if denied:
            return denied
        query = self._query()
        if not query:
            return _ok([])
        active = DmeProduct.objects.filter(active=True)
        rows = list(active.filter(code__istartswith=query).order_by("code")[:RESULT_LIMIT])
        seen = {r.id for r in rows}
        rows += [
            r for r in active.filter(name__icontains=query).order_by("name")[:RESULT_LIMIT] if r.id not in seen
        ]
        return _ok([dme_product_ref(r) for r in rows[:RESULT_LIMIT]])

    @api.get("/lab-partners")
    def lab_partners(self) -> list[Response | Effect]:
        """The instance's lab partners."""
        denied = self._forbidden()
        if denied:
            return denied
        return _ok(
            [{"id": str(p.id), "display": p.name} for p in LabPartner.objects.order_by("name")]
        )

    @api.get("/lab-tests/<partner_id>")
    def lab_tests(self) -> list[Response | Effect]:
        """Tests one lab partner offers."""
        denied = self._forbidden()
        if denied:
            return denied
        partner = LabPartner.objects.filter(id=self.request.path_params["partner_id"]).first()
        if partner is None:
            return _ok([])
        tests = partner.available_tests.all()
        query = self._query()
        if query:
            tests = tests.filter(order_name__icontains=query)
        return _ok(
            [
                {"code": test.order_code, "display": test.order_name}
                for test in tests.order_by("order_name")[:100]
            ]
        )

    @api.get("/assignees")
    def assignees(self) -> list[Response | Effect]:
        """Active staff and teams a task can be assigned to, keyed by dbid as tasks require."""
        denied = self._forbidden()
        if denied:
            return denied
        staff = [
            {"to": "staff", "id": s.dbid, "display": f"{s.first_name} {s.last_name}".strip()}
            for s in Staff.objects.filter(active=True).order_by("first_name", "last_name")
        ]
        teams = [{"to": "team", "id": t.dbid, "display": t.name} for t in Team.objects.order_by("name")]
        return _ok(teams + staff)
