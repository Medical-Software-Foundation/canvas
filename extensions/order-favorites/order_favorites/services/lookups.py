"""Searches against Canvas's medication, pharmacy, and diagnosis services.

Medication search uses FDB through ontologies (carried over from prescription-favorites), pharmacy
search uses the pharmacy service, and diagnosis search uses the same science endpoint as Canvas's
Diagnose command. Science returns ICD-10 codes without the dot (E119); codes are stored that way,
which Canvas accepts for lab orders, and shown with the dot (E11.9).

A failed request raises LookupFailed so the API can answer 503 instead of an empty list that looks
like "no matches".
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.utils.http import ontologies_http, pharmacy_http, science_http
from requests import RequestException

MAX_RESULTS = 20
ICD10_CODE = re.compile(r"^[A-Z][0-9][0-9A-Z]{1,5}$")


class LookupFailed(Exception):
    """A Canvas lookup service didn't answer."""


def icd10_display(code: str) -> str:
    """E119 -> E11.9. Codes of three characters have no dot."""
    code = (code or "").replace(".", "").upper()
    return code if len(code) <= 3 else f"{code[:3]}.{code[3:]}"


def normalize_icd10(code: str) -> str:
    return (code or "").replace(".", "").strip().upper()


def _get(client: Any, path: str) -> dict[str, Any]:
    try:
        body = client.get_json(path).json()
    except (RequestException, ValueError) as exc:
        raise LookupFailed(str(exc)) from exc
    return body if isinstance(body, dict) else {}


def search_medications(query: str) -> list[dict[str, Any]]:
    body = _get(ontologies_http, f"/fdb/grouped-medication/?{urlencode({'search': query})}")
    medications = []
    for med in body.get("results", [])[:MAX_RESULTS]:
        medications.append(
            {
                "fdb_code": str(med.get("med_medication_id", "")),
                "name": med.get("med_medication_description", ""),
                "units": [
                    {
                        "representative_ndc": cq.get("representative_ndc", ""),
                        "ncpdp_quantity_qualifier_code": cq.get("erx_ncpdp_script_quantity_qualifier_code", ""),
                        "description": cq.get("clinical_quantity_description", ""),
                    }
                    for cq in med.get("clinical_quantities", [])
                    if cq.get("representative_ndc") and cq.get("erx_ncpdp_script_quantity_qualifier_code")
                ],
            }
        )
    return medications


def search_pharmacies(query: str) -> list[dict[str, str]]:
    try:
        results = pharmacy_http.search_pharmacies(query)
    except (RequestException, ValueError) as exc:
        raise LookupFailed(str(exc)) from exc
    pharmacies = []
    for pharm in results[:MAX_RESULTS]:
        street = ", ".join(p for p in (pharm.get("address_line_1", ""), pharm.get("address_line_2", "")) if p)
        city = f"{pharm.get('city', '')}, {pharm.get('state', '')} {pharm.get('zip_code', '')}".strip(", ")
        pharmacies.append(
            {
                "ncpdp_id": str(pharm.get("ncpdp_id", "")),
                "name": pharm.get("organization_name", ""),
                "address": f"{street}, {city}" if street else city,
            }
        )
    return pharmacies


def search_diagnoses(query: str) -> list[dict[str, str]]:
    """ICD-10 codes matching a code or words, as [{code, text}], one row per code."""
    body = _get(science_http, f"/search/condition/?{urlencode({'query': query, 'limit': 50})}")
    seen: set[str] = set()
    results = []
    for row in body.get("results", []):
        code = normalize_icd10(row.get("icd10_code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        results.append({"code": code, "text": row.get("icd10_text") or row.get("preferred_snomed_term") or ""})
        if len(results) >= MAX_RESULTS:
            break
    return results


def find_diagnosis(code: str) -> dict[str, str] | None:
    """The ICD-10 code's name, if science knows the exact code."""
    code = normalize_icd10(code)
    if not ICD10_CODE.match(code):
        return None
    for row in search_diagnoses(icd10_display(code)):
        if row["code"] == code:
            return row
    return None


def find_medication(value: str) -> tuple[dict[str, Any] | None, str]:
    """One FDB medication from its exact name or FDB code, for import. Never guesses between several."""
    value = value.strip()
    if not value:
        return None, "the medication is missing"
    meds = search_medications(value)
    exact = [m for m in meds if m["fdb_code"] == value or m["name"].lower() == value.lower()]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, f"more than one medication is named {value}; use its FDB code"
    return None, f"no medication is named exactly {value}; copy the name from the medication search"
