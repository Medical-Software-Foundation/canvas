"""Resolve a medication's RxNorm code via Canvas's Ontologies service.

Photon's catalog matches on RxNorm (`rxcui`), while the Canvas prescribe command
carries an NDC. This bridges the two so the API-direct send can match medications
by code instead of fuzzy name.
"""

from __future__ import annotations

from canvas_sdk.utils.http import ontologies_http
from logger import log


def ndc_to_rxcui(ndc: str | None) -> str | None:
    """Return the RxNorm rxcui for an NDC, or None when it can't be resolved."""
    if not ndc:
        return None
    try:
        response = ontologies_http.get_json(f"/fdb/ndc-to-medication/{ndc}/")
    except Exception as exc:  # noqa: BLE001 - ontology lookup is best-effort
        log.warning("Ontologies NDC lookup failed for %s: %s", ndc, exc)
        return None
    if getattr(response, "status_code", None) != 200:
        return None
    rxcui = (response.json() or {}).get("rxnorm_rxcui")
    return str(rxcui) if rxcui else None
