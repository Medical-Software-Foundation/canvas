"""Create a DocumentReference on a patient via the Canvas FHIR client.

The PDF is embedded inline as base64 (no S3). On create, Canvas requires `type`
(LOINC), `category` (Canvas category system, derived from the chosen type), and three
extensions: clinical date, reviewer, and requires-signature.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.utils.http import Http

from capture.utils.constants import (
    CATEGORY_SYSTEM,
    CLINICAL_DATE_EXTENSION,
    DOCUMENT_TYPES,
    LOINC_SYSTEM,
    REQUIRES_SIGNATURE_EXTENSION,
    REVIEW_MODE_EXTENSION,
    REVIEW_MODE_NOT_REQUIRED,
    REVIEWER_EXTENSION,
)


def build_document_reference_payload(
    patient_id: str,
    document_type_key: str,
    title: str,
    pdf_bytes: bytes,
    reviewer_id: str,
    clinical_date: str,
    requires_signature: bool = False,
) -> dict:
    """Build the FHIR DocumentReference payload for an inline-base64 PDF."""
    type_info = DOCUMENT_TYPES[document_type_key]
    encoded = base64.b64encode(pdf_bytes).decode("ascii")

    return {
        "resourceType": "DocumentReference",
        "extension": [
            {
                "url": CLINICAL_DATE_EXTENSION,
                "valueDate": clinical_date,
            },
            {
                "url": REVIEWER_EXTENSION,
                "valueReference": {
                    "reference": f"Practitioner/{reviewer_id}",
                    "type": "Practitioner",
                },
            },
            {
                "url": REQUIRES_SIGNATURE_EXTENSION,
                "valueBoolean": requires_signature,
            },
            {
                "url": REVIEW_MODE_EXTENSION,
                "valueCode": REVIEW_MODE_NOT_REQUIRED,
            },
        ],
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": LOINC_SYSTEM,
                    "code": type_info["loinc_code"],
                    "display": type_info["loinc_display"],
                }
            ],
            "text": type_info["loinc_display"],
        },
        "category": [
            {
                "coding": [
                    {
                        "system": CATEGORY_SYSTEM,
                        "code": type_info["category_code"],
                    }
                ]
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "description": title,
        "content": [
            {
                "attachment": {
                    "contentType": "application/pdf",
                    "data": encoded,
                    "title": title,
                }
            }
        ],
    }


def create_document_reference(
    client_id: str,
    client_secret: str,
    patient_id: str,
    document_type_key: str,
    title: str,
    pdf_bytes: bytes,
    reviewer_id: str,
    clinical_date: str | None = None,
    requires_signature: bool = False,
) -> str:
    """Create the DocumentReference and return its server-assigned id.

    clinical_date defaults to today (UTC) in YYYY-MM-DD format.
    """
    if not clinical_date:
        clinical_date = datetime.now(timezone.utc).date().isoformat()

    payload = build_document_reference_payload(
        patient_id=patient_id,
        document_type_key=document_type_key,
        title=title,
        pdf_bytes=pdf_bytes,
        reviewer_id=reviewer_id,
        clinical_date=clinical_date,
        requires_signature=requires_signature,
    )

    # We POST directly rather than via CanvasFhir.create(): Canvas returns 201 with an
    # empty body (the new id is in the Location header), and CanvasFhir.create() calls
    # response.json() unconditionally, which raises on the empty body. We reuse the
    # client only for its cached OAuth headers and base URL.
    client = CanvasFhir(client_id, client_secret)
    response = Http().post(
        f"{client._base_url}/DocumentReference",
        headers=client._get_headers(),
        json=payload,
    )
    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface the fumage OperationOutcome body
        body = getattr(response, "text", "")
        raise RuntimeError(f"{exc} | body={body[:1000]}") from exc

    # The new id is in the Location header, e.g.
    # https://fumage-…/DocumentReference/<id>/_history/1 — take the segment right
    # after "DocumentReference".
    location = response.headers.get("Location") or response.headers.get("location") or ""
    parts = location.rstrip("/").split("/")
    if "DocumentReference" in parts:
        idx = parts.index("DocumentReference")
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    return parts[-1] if location else ""
