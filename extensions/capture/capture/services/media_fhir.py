"""Create a FHIR Media on a patient's note (encounter) via the Canvas FHIR client.

A clinical image is attached to a note by creating a `Media` resource linked to the
note's encounter — `subject` is the patient, `encounter` is the note's encounter, and
the image is embedded inline as base64. Mirrors `document_fhir.create_document_reference`.
"""

from __future__ import annotations

import base64

from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.utils.http import Http


def build_media_payload(
    patient_id: str,
    encounter_id: str,
    image_bytes: bytes,
    content_type: str,
    title: str,
) -> dict:
    """Build the FHIR Media payload for an inline-base64 image on a note's encounter."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "resourceType": "Media",
        "status": "completed",
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "content": {
            "contentType": content_type,
            "data": encoded,
            "title": title or "Clinical photo",
        },
    }


def create_media(
    client_id: str,
    client_secret: str,
    patient_id: str,
    encounter_id: str,
    image_bytes: bytes,
    content_type: str,
    title: str = "Clinical photo",
) -> str:
    """Create the Media and return its server-assigned id.

    POSTs directly (like the DocumentReference path) so an empty 201 body with the id
    in the Location header is handled gracefully.
    """
    payload = build_media_payload(
        patient_id=patient_id,
        encounter_id=encounter_id,
        image_bytes=image_bytes,
        content_type=content_type,
        title=title,
    )

    client = CanvasFhir(client_id, client_secret)
    response = Http().post(
        f"{client._base_url}/Media",
        headers=client._get_headers(),
        json=payload,
    )
    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface the fumage OperationOutcome body
        body = getattr(response, "text", "")
        raise RuntimeError(f"{exc} | body={body[:1000]}") from exc

    location = response.headers.get("Location") or response.headers.get("location") or ""
    parts = location.rstrip("/").split("/")
    if "Media" in parts:
        idx = parts.index("Media")
        return parts[idx + 1] if idx + 1 < len(parts) else ""
    return parts[-1] if location else ""
