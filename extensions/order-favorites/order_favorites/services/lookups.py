"""Searches against Canvas's medication, pharmacy, diagnosis, and imaging services.

Medication search uses FDB through ontologies (carried over from prescription-favorites), pharmacy
search uses the pharmacy service, and diagnosis search uses the same science endpoint as Canvas's
Diagnose command. Science returns ICD-10 codes without the dot (E119); codes are stored that way,
which Canvas accepts for lab and imaging orders, and shown with the dot (E11.9).

Imaging study and imaging center searches use the same science endpoints as Canvas's Imaging Order
command. When an imaging order arrives with an image code, Canvas searches imaging studies for that
code and fills the Image field from the FIRST result, or leaves it blank when there is none.
check_image runs that same search, so an imaging favorite is only saved or added when its code
still leads to its own study.

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


IMAGING_SEARCH_LIMIT = 25  # what Canvas's Imaging Order command asks science for
CENTER_FIELDS = (
    ("first_name", "firstName"),
    ("last_name", "lastName"),
    ("specialty", "specialty"),
    ("practice_name", "practiceName"),
    ("business_fax", "businessFax"),
    ("business_phone", "businessPhone"),
    ("business_address", "businessAddress"),
    ("notes", "notes"),
)


def _science_results(path: str) -> list[dict[str, Any]]:
    """The results list of a science search. Anything but a 2xx answer with a results list raises
    LookupFailed, so an outage never reads as "no matches"."""
    try:
        response = science_http.get_json(path)
        body = response.json()
    except (RequestException, ValueError) as exc:
        raise LookupFailed(str(exc)) from exc
    if response.status_code >= 400 or not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise LookupFailed(f"science answered {response.status_code}")
    return [row for row in body["results"] if isinstance(row, dict)]


def _imaging_rows(query: str) -> list[dict[str, str]]:
    path = "/parse-templates/imaging-reports/?" + urlencode({"query": query, "limit": IMAGING_SEARCH_LIMIT})
    return [
        {"code": str(row.get("code") or "").strip(), "code_system": str(row.get("code_system") or "").strip(), "name": str(row.get("name") or "").strip()}
        for row in _science_results(path)
    ]


def search_imaging(query: str) -> list[dict[str, str]]:
    """Imaging studies matching a code or words, as [{code, code_system, name}], one row per study."""
    seen: set[tuple[str, str]] = set()
    results = []
    for row in _imaging_rows(query):
        key = (row["code_system"], row["code"])
        if not row["code"] or not row["name"] or key in seen:
            continue
        seen.add(key)
        results.append(row)
        if len(results) >= MAX_RESULTS:
            break
    return results


def check_image(
    image_code: str,
    code_system: str = "",
    cache: dict[tuple[str, str], dict[str, str] | None] | None = None,
) -> dict[str, str] | None:
    """The study Canvas will put in the Image field for this image code, or None when that would be
    blank or a different study.

    Canvas takes the first result of an imaging search for the code. It resolves when that first
    result has this code, and this code system when one is given. Raises LookupFailed when science
    doesn't answer. cache, when given, holds answers already fetched in the same request, so a code
    is searched once however many favorites use it.
    """
    image_code = (image_code or "").strip()
    if not image_code:
        return None
    if cache is not None:
        key = (image_code, code_system)
        if key not in cache:
            cache[key] = check_image(image_code, code_system)
        return cache[key]
    rows = _imaging_rows(image_code)
    first = rows[0] if rows else None
    if first is None or first["code"] != image_code or not first["name"]:
        return None
    if code_system and first["code_system"] != code_system:
        return None
    return first


def search_imaging_centers(query: str) -> list[dict[str, str]]:
    """Radiology centers matching a name, as the fields of an order's imaging center. Searched the
    same way as the Imaging Order command's Imaging center field, without its service-area zip codes."""
    path = "/contacts/?" + urlencode({"search": query, "job_title__icontains": "radiology"})
    results = []
    for row in _science_results(path):
        center = {field: str(row.get(source) or "").strip() for field, source in CENTER_FIELDS}
        if center["practice_name"] or center["last_name"]:
            results.append(center)
        if len(results) >= MAX_RESULTS:
            break
    return results


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
