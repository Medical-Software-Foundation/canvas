"""Resolve a medication's RxNorm code via Canvas's Ontologies service.

Photon's catalog matches on RxNorm (`rxcui`), while the Canvas prescribe command
carries an NDC. This bridges the two so the API-direct send can match medications
by code instead of fuzzy name.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.utils.http import ontologies_http
from logger import log


def _rxcui_from(payload: Any) -> str | None:
    """Pull rxnorm_rxcui out of an Ontologies response (object/list/results)."""
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            results = payload["results"]
            payload = results[0] if results else {}
        rxcui = payload.get("rxnorm_rxcui")
        return str(rxcui) if rxcui else None
    return None


def _lookup(path: str, label: str) -> str | None:
    try:
        response = ontologies_http.get_json(path)
    except OSError as exc:
        # Network/timeout/HTTP failure reaching the Ontologies service degrades to
        # "no rxcui" (the Rx is flagged for the Elements modal). We catch OSError —
        # the base class of requests' RequestException — rather than importing
        # `requests` (which the plugin sandbox disallows). Other errors surface.
        log.warning("Ontologies %s lookup failed (%s): %s", label, path, exc)
        return None
    if getattr(response, "status_code", None) != 200:
        return None
    return _rxcui_from(response.json())


def fdb_to_rxcui(fdb_code: str | None) -> str | None:
    """Return the RxNorm rxcui for an FDB code (med_medication_id), or None."""
    if not fdb_code:
        return None
    return _lookup(f"/fdb/grouped-medication/{fdb_code}/", "FDB")


def ndc_to_rxcui(ndc: str | None) -> str | None:
    """Return the RxNorm rxcui for an NDC, or None when it can't be resolved."""
    if not ndc:
        return None
    return _lookup(f"/fdb/ndc-to-medication/{ndc}/", "NDC")
