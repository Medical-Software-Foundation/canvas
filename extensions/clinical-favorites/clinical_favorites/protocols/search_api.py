"""Search endpoints for FDB medications, ICD-10 conditions, and pharmacies."""

from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.utils.http import ontologies_http, pharmacy_http
from logger import log


# Canvas plugin sandbox blocks `from requests.exceptions import ...` and also
# blocks the `type` builtin, so we catch by inheritance. Both stdlib
# ConnectionError and requests ConnectionError and Timeout all extend OSError,
# which is available in the sandbox as a stdlib builtin.


def _medication_match_rank(description: str, query: str) -> tuple[int, int, str]:
    """Rank an FDB row by how its description matches the typed term.

    FDB returns rows in its own order, which can float a brand name ahead of
    the generic the clinician typed. We re rank so the typed term wins. Lower
    is better. The tie breakers prefer the shorter, alphabetically earlier
    description so a plain generic outranks a longer branded combination.
    """
    desc = (description or "").casefold()
    q = (query or "").casefold().strip()
    if not desc or not q:
        rank = 5
    elif desc == q:
        rank = 0
    elif desc.startswith(q):
        rank = 1
    elif any(token.startswith(q) for token in desc.split()):
        rank = 2
    elif q in desc:
        rank = 3
    else:
        rank = 4
    return (rank, len(desc), desc)


class MedicationSearchAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """FDB medication search with two hop hydration."""

    PATH = "/routes/search/medication"

    def get(self) -> list[Response | Effect]:
        query = self.request.query_params.get("q", "").strip()
        if len(query) < 2:
            return [JSONResponse({"results": [], "success": True})]

        try:
            list_payload = ontologies_http.get_json(
                f"/fdb/grouped-medication/?{urlencode({'search': query})}"
            ).json()
        except OSError as exc:
            log.warning(f"FDB list search unreachable, {exc}")
            return [
                JSONResponse(
                    {
                        "results": [],
                        "success": False,
                        "error": "Medication search temporarily unavailable",
                    },
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]
        except Exception as exc:
            log.error(f"FDB list search failed, {exc}")
            return [
                JSONResponse(
                    {
                        "results": [],
                        "success": False,
                        "error": "Medication search failed",
                    },
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        ranked_rows = sorted(
            list_payload.get("results", []),
            key=lambda row: _medication_match_rank(
                row.get("med_medication_description", ""), query
            ),
        )

        results: list[dict[str, Any]] = []
        for row in ranked_rows[:20]:
            med_id = row.get("med_medication_id")
            if not med_id:
                continue

            clinical_quantities: list[dict[str, Any]] = []
            try:
                detail = ontologies_http.get_json(
                    f"/fdb/grouped-medication/{med_id}"
                ).json()
                seen: set[str] = set()
                for cq in detail.get("clinical_quantities", []):
                    desc = cq.get("clinical_quantity_description", "")
                    if desc and desc not in seen:
                        seen.add(desc)
                        clinical_quantities.append({
                            "representative_ndc": cq.get("representative_ndc", ""),
                            "ncpdp_quantity_qualifier_code": cq.get(
                                "erx_ncpdp_script_quantity_qualifier_code", ""
                            ),
                            "quantity_description": desc,
                            "erx_quantity": cq.get("erx_quantity", "1.0"),
                        })
                clinical_quantities.sort(key=lambda x: len(x["quantity_description"]))
            except Exception as exc:
                log.warning(f"FDB detail hydration failed for {med_id}, {exc}")

            results.append({
                "fdb_code": str(med_id),
                "display_name": row.get("med_medication_description", ""),
                "clinical_quantities": clinical_quantities,
            })

        return [JSONResponse({"results": results, "success": True})]


class ConditionSearchAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """ICD-10 condition search."""

    PATH = "/routes/search/condition"

    def get(self) -> list[Response | Effect]:
        query = self.request.query_params.get("q", "").strip()
        if len(query) < 2:
            return [JSONResponse({"results": [], "success": True})]

        try:
            payload = ontologies_http.get_json(
                f"/icd/condition?{urlencode({'search': query})}"
            ).json()
        except OSError as exc:
            log.warning(f"ICD-10 search unreachable, {exc}")
            return [
                JSONResponse(
                    {
                        "results": [],
                        "success": False,
                        "error": "Condition search temporarily unavailable",
                    },
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]
        except Exception as exc:
            log.error(f"ICD-10 search failed, {exc}")
            return [
                JSONResponse(
                    {
                        "results": [],
                        "success": False,
                        "error": "Condition search failed",
                    },
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        results = [
            {"code": r.get("icd10_code", ""), "display": r.get("icd10_text", "")}
            for r in payload.get("results", [])[:30]
            if r.get("icd10_code") and r.get("icd10_text")
        ]
        return [JSONResponse({"results": results, "success": True})]


class PharmacySearchAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Pharmacy search by name, retained from prescription-favorites."""

    PATH = "/routes/search/pharmacy"

    def get(self) -> list[Response | Effect]:
        query = self.request.query_params.get("q", "").strip()
        if len(query) < 2:
            return [JSONResponse({"results": [], "success": True})]

        try:
            rows = pharmacy_http.search_pharmacies(query)
        except OSError as exc:
            log.warning(f"Pharmacy service unreachable, {exc}")
            return [
                JSONResponse(
                    {
                        "results": [],
                        "success": False,
                        "error": "Pharmacy search temporarily unavailable",
                    },
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            ]
        except Exception as exc:
            log.error(f"Pharmacy search failed, {exc}")
            return [
                JSONResponse(
                    {
                        "results": [],
                        "success": False,
                        "error": "Pharmacy search failed",
                    },
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

        results = []
        for row in rows[:20]:
            address_line = ", ".join(
                p for p in [row.get("address_line_1", ""), row.get("address_line_2", "")] if p
            )
            city_state_zip = f"{row.get('city', '')}, {row.get('state', '')} {row.get('zip_code', '')}".strip(", ")
            full_address = f"{address_line}, {city_state_zip}" if address_line else city_state_zip
            results.append({
                "ncpdp_id": row.get("ncpdp_id", ""),
                "organization_name": row.get("organization_name", ""),
                "address": full_address.strip(", "),
                "phone_primary": row.get("phone_primary", ""),
            })
        return [JSONResponse({"results": results, "success": True})]
