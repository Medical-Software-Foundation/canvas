"""Document-backed portal content: labs, imaging, letters.

All three are exposed by the FHIR API as DocumentReferences, each pointing at a
rendered PDF. (Lab and imaging reports are not in the SDK data tables as
documents - the FHIR layer renders them.) Listing and PDF streaming go through
``portal_content.shared.fhir_documents``; this module just maps a portal
component to its FHIR category code.
"""

from __future__ import annotations

from portal_content.shared.fhir_documents import search_documents

# Portal component -> FHIR DocumentReference category code.
CATEGORY_CODES = {
    "labs": "labreport",
    "imaging": "imagingreport",
    "letters": "correspondence",
}


def list_documents(
    host: str, client_id: str, client_secret: str, patient_id: str, component: str
) -> list[dict]:
    """List the patient's documents for a portal component (newest first)."""
    return search_documents(host, client_id, client_secret, patient_id, CATEGORY_CODES[component])
