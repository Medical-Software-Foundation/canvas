"""Set a patient's profile photo (avatar) via the Canvas FHIR client.

`Patient.photo` is writable on update. We read the current Patient resource, inject the
new `photo[].data` (base64), and PUT it back (read-modify-write) so no other fields are
dropped.
"""

from __future__ import annotations

import base64

from canvas_sdk.clients.canvas_fhir import CanvasFhir
from canvas_sdk.utils.http import Http


def update_patient_photo(
    client_id: str,
    client_secret: str,
    patient_id: str,
    image_bytes: bytes,
    content_type: str,
) -> str:
    """Read the Patient, set its photo, and PUT it back. Returns the patient id."""
    client = CanvasFhir(client_id, client_secret)

    # Read the full current resource so the update doesn't drop other fields.
    resource = client.read("Patient", patient_id)
    if not isinstance(resource, dict) or resource.get("resourceType") != "Patient":
        raise RuntimeError(f"Unexpected Patient read response: {str(resource)[:500]}")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    resource["photo"] = [{"contentType": content_type, "data": encoded}]

    # PUT directly (rather than CanvasFhir.update) so an empty 200 body doesn't trip
    # an unconditional response.json().
    response = Http().put(
        f"{client._base_url}/Patient/{patient_id}",
        headers=client._get_headers(),
        json=resource,
    )
    try:
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface the fumage OperationOutcome body
        body = getattr(response, "text", "")
        raise RuntimeError(f"{exc} | body={body[:1000]}") from exc

    return patient_id
