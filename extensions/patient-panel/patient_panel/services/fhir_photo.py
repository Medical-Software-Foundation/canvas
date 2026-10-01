"""FHIR URL building + patient-photo response parsing.

Pure helpers extracted from the photo endpoint. The OAuth token and its cache
stay on the API class; these take the already-resolved token / http client.
"""

import base64
from typing import Any

from logger import log


def build_token_url(instance_url: str) -> str:
    """Build the OAuth token URL from the configured instance URL.

    The token endpoint lives on the EMR host, not the fumage host, so strip a
    leading `fumage-` if present.
    """
    instance_url = instance_url.strip('"\'').rstrip("/")
    if "fumage-" in instance_url:
        emr_url = instance_url.replace("https://fumage-", "https://")
    else:
        emr_url = instance_url
    return f"{emr_url}/auth/token/"


def build_patient_fhir_url(instance_url: str, patient_id: str) -> str:
    """Build the fumage FHIR Patient URL from the configured instance URL."""
    instance_url = instance_url.strip('"\'').rstrip("/")
    if "fumage-" not in instance_url:
        instance_url = instance_url.replace("https://", "https://fumage-")
    return f"{instance_url}/Patient/{patient_id}"


def parse_photo_response(
    patient_data: dict[str, Any],
    token: str,
    http: Any,
    patient_id: str,
) -> tuple[str, bytes] | None:
    """Extract photo bytes from a FHIR Patient resource.

    Handles inline base64 (`photo[0].data`) and the presigned-URL form
    (`photo[0].url`). Logs the decision branch so production traces show *why*
    the default avatar fell through.
    """
    photos = patient_data.get("photo", [])
    if not photos:
        log.info(f"[photo] {patient_id}: FHIR returned empty photo[]")
        return None

    photo = photos[0]
    if photo.get("data"):
        content_type = photo.get("contentType", "image/jpeg")
        data = base64.b64decode(photo["data"])
        log.info(f"[photo] {patient_id}: served inline base64 ({content_type})")
        return (content_type, data)

    if photo.get("url"):
        # Canvas's fumage /files/photo endpoint 307-redirects to a presigned
        # S3 URL. canvas_sdk Http (requests.Session) follows redirects
        # automatically, and requests strips the Authorization header on the
        # cross-host hop to S3 — so the Bearer token authenticates the fumage
        # request without leaking to S3, and the final response is the 200.
        photo_response = http.get(
            photo["url"],
            headers={"Authorization": f"Bearer {token}"},
        )
        if photo_response.status_code == 200:
            content_type = photo_response.headers.get("Content-Type", "image/jpeg")
            log.info(
                f"[photo] {patient_id}: served from url ({content_type}, "
                f"{len(photo_response.content)} bytes)"
            )
            return (content_type, photo_response.content)
        log.error(f"[photo] {patient_id}: photo url fetch {photo_response.status_code}")
        return None

    log.info(f"[photo] {patient_id}: photo[0] has neither data nor url")
    return None
