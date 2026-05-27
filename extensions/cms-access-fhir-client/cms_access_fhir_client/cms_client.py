"""Thin wrapper around the CMS ACCESS FHIR API operations.

URL structure (per User Guide):
    <ACCESS_BASE_URL>/access/<resourceType>/<operation>?entityId=<entityId>

Real example:
    https://impl-cdxapi.cmmi.cms.gov/cdx/services/fhir/access/Patient/$check-eligibility?entityId=ACCES10098

``ACCESS_BASE_URL`` should be set to the path up to (but not including) ``/access``, e.g.:
    https://impl-cdxapi.cmmi.cms.gov/cdx/services/fhir

All async operation POSTs require ``Prefer: respond-async``.

Implementation notes:
- The SDK ``Http`` client does not accept a ``params=`` kwarg, so entityId is
  embedded in the URL path.
- Headers must be passed per-call (``Http`` doesn't read instance attributes
  like ``http.headers = {...}``).
- ``urljoin`` requires the base URL to end with ``/`` or it strips the last
  path segment, so we normalize the base URL in ``_build_http``.
"""
from urllib.parse import quote

from canvas_sdk.utils import Http
from cms_access_fhir_client.oauth import get_access_token

# The model ID is always "access" for the CMS ACCESS model (case-insensitive per User Guide).
_MODEL_ID = "access"

# Required by the User Guide on every async operation POST.
_PREFER_ASYNC = "respond-async"


def _build_http(secrets: dict) -> tuple[Http, dict]:
    """Return (Http instance, headers dict). Fails closed on missing BASE_URL."""
    base_url = secrets.get("ACCESS_BASE_URL")
    if not base_url:
        raise ValueError("Missing required secret: ACCESS_BASE_URL")
    # urljoin treats the last path segment as a "file" and replaces it when the
    # base lacks a trailing slash — normalize so relative paths resolve correctly.
    if not base_url.endswith("/"):
        base_url = base_url + "/"
    token = get_access_token(secrets)
    http = Http(base_url=base_url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/fhir+json",
        "Prefer": _PREFER_ASYNC,
    }
    return http, headers


def _parse_operation_outcome(body: dict) -> str:
    """Extract the first issue detail text from a FHIR OperationOutcome body."""
    issues = body.get("issue", [])
    if issues:
        return issues[0].get("details", {}).get("text", "Unknown error")
    return "Unknown error"


def _operation_url(operation: str, participant_id: str) -> str:
    """Build the operation URL relative to the (slash-terminated) base URL."""
    return f"{_MODEL_ID}/Patient/${operation}?entityId={quote(participant_id)}"


def check_eligibility(secrets: dict, mbi: str, payer_id: str, track: str) -> dict:
    """POST $check-eligibility and return the response body dict.

    CMS requires four flat top-level parameters: participantID, payerID, track, mbi.
    The nested Patient resource is NOT sent — CMS resolves the patient by MBI on
    their side.

    On 400, parses the OperationOutcome and raises RuntimeError with the detail text.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "participantID", "valueString": participant_id},
            {"name": "payerID", "valueString": payer_id},
            {"name": "track", "valueCode": track},
            {"name": "mbi", "valueString": mbi},
        ],
    }
    response = http.post(
        _operation_url("check-eligibility", participant_id),
        json=payload,
        headers=headers,
    )

    if response.status_code == 400:
        detail = _parse_operation_outcome(response.json())
        raise RuntimeError(f"$check-eligibility pre-validation failed: {detail}")

    if not response.ok:
        raise RuntimeError(
            f"$check-eligibility failed: HTTP {response.status_code} {response.text[:200]}"
        )
    return response.json()


def align(
    secrets: dict,
    mbi: str,
    payer_id: str,
    track: str,
    clinical_justification: str,
) -> tuple[int, str | None, dict]:
    """POST $align. Returns (status_code, content_location_url, body_dict).

    CMS requires four flat top-level parameters (participantID, payerID, track, mbi)
    plus clinicalJustification. The nested Patient resource is NOT sent.

    202 means async — caller should store content_location_url and poll.
    On 400, raises RuntimeError with the OperationOutcome detail text.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "participantID", "valueString": participant_id},
            {"name": "payerID", "valueString": payer_id},
            {"name": "track", "valueCode": track},
            {"name": "mbi", "valueString": mbi},
            {"name": "clinicalJustification", "valueString": clinical_justification},
        ],
    }
    response = http.post(
        _operation_url("align", participant_id),
        json=payload,
        headers=headers,
    )

    if response.status_code == 400:
        detail = _parse_operation_outcome(response.json())
        raise RuntimeError(f"$align pre-validation failed: {detail}")

    if not response.ok:
        raise RuntimeError(
            f"$align failed: HTTP {response.status_code} {response.text[:200]}"
        )
    content_location = response.headers.get("Content-Location")
    body = response.json() if response.text else {}
    return response.status_code, content_location, body


def unalign(
    secrets: dict,
    mbi: str,
    payer_id: str,
    track: str,
    alignment_id: str,
    reason_code: str,
) -> tuple[int, str | None, dict]:
    """POST $unalign. Returns (status_code, content_location_url, body_dict).

    CMS requires the full flat parameter set (participantID, payerID, track, mbi)
    plus alignmentId and reasonCode.

    On 400, raises RuntimeError with the OperationOutcome detail text.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "participantID", "valueString": participant_id},
            {"name": "payerID", "valueString": payer_id},
            {"name": "track", "valueCode": track},
            {"name": "mbi", "valueString": mbi},
            {"name": "alignmentId", "valueString": alignment_id},
            {"name": "reasonCode", "valueCode": reason_code},
        ],
    }
    response = http.post(
        _operation_url("unalign", participant_id),
        json=payload,
        headers=headers,
    )

    if response.status_code == 400:
        detail = _parse_operation_outcome(response.json())
        raise RuntimeError(f"$unalign pre-validation failed: {detail}")

    if not response.ok:
        raise RuntimeError(
            f"$unalign failed: HTTP {response.status_code} {response.text[:200]}"
        )
    content_location = response.headers.get("Content-Location")
    body = response.json() if response.text else {}
    return response.status_code, content_location, body


def report_data(secrets: dict, patient_fhir_id: str, alignment_id: str) -> tuple[int, str | None, dict]:
    """POST $report-data (stub — payload not yet specified in IG v0.9.1).

    TODO: Implement full payload once IG v0.9.6+ is published.
    """
    raise NotImplementedError(
        "$report-data payload is not yet specified in CMS ACCESS IG v0.9.1. "
        "Implement once IG v0.9.6+ is published."
    )


def poll_submission_status(secrets: dict, status_url: str) -> tuple[int, dict]:
    """GET a submission-status URL returned in a Content-Location header.

    Returns (status_code, body_dict).

    Per the User Guide:
    - 202 + empty body + X-Progress header  → still processing
    - 200 + Parameters body                 → completed successfully
    - 200 + OperationOutcome body           → completed with errors

    Does NOT call raise_for_status() so the caller can branch on 202.
    """
    token = get_access_token(secrets)
    http = Http()
    headers = {"Authorization": f"Bearer {token}"}
    response = http.get(status_url, headers=headers)

    # 202 is expected (async in-progress) — don't raise on it
    if response.status_code not in (200, 202):
        response.raise_for_status()

    body = response.json() if response.text else {}
    return response.status_code, body
