"""Thin wrapper around the CMS ACCESS FHIR API operations."""
from canvas_sdk.utils import Http
from cms_access_fhir_client.oauth import get_access_token


def _build_http(secrets: dict) -> tuple[Http, str]:
    """Return (Http instance, base_url). Fails closed on missing BASE_URL."""
    base_url = secrets.get("ACCESS_BASE_URL")
    if not base_url:
        raise ValueError("Missing required secret: ACCESS_BASE_URL")
    token = get_access_token(secrets)
    http = Http(base_url=base_url)
    http.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/fhir+json"}
    return http, base_url


def check_eligibility(secrets: dict, patient_fhir_id: str) -> dict:
    """POST $check-eligibility and return the response body dict."""
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, _ = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "participant", "valueString": participant_id},
            {"name": "patient", "valueReference": {"reference": f"Patient/{patient_fhir_id}"}},
        ],
    }
    response = http.post("/Patient/$check-eligibility", json=payload)
    response.raise_for_status()
    return response.json()


def align(
    secrets: dict,
    patient_fhir_id: str,
    track: str,
    clinical_justification: str,
) -> tuple[int, str | None, dict]:
    """POST $align. Returns (status_code, content_location_url, body_dict).

    202 means async — caller should store content_location_url and poll.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, _ = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "participant", "valueString": participant_id},
            {"name": "patient", "valueReference": {"reference": f"Patient/{patient_fhir_id}"}},
            {"name": "track", "valueCode": track},
            {"name": "clinicalJustification", "valueString": clinical_justification},
        ],
    }
    response = http.post("/Patient/$align", json=payload)
    response.raise_for_status()
    content_location = response.headers.get("Content-Location")
    body = response.json() if response.text else {}
    return response.status_code, content_location, body


def unalign(
    secrets: dict,
    patient_fhir_id: str,
    alignment_id: str,
    reason_code: str,
) -> tuple[int, str | None, dict]:
    """POST $unalign. Returns (status_code, content_location_url, body_dict)."""
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, _ = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "participant", "valueString": participant_id},
            {"name": "alignmentId", "valueString": alignment_id},
            {"name": "reasonCode", "valueCode": reason_code},
        ],
    }
    response = http.post("/Patient/$unalign", json=payload)
    response.raise_for_status()
    content_location = response.headers.get("Content-Location")
    body = response.json() if response.text else {}
    return response.status_code, content_location, body


def report_data(secrets: dict, patient_fhir_id: str, alignment_id: str) -> tuple[int, str | None, dict]:
    """POST $report-data (stub — payload not yet specified in IG v0.9.1).

    TODO: Implement full payload once IG v0.9.6+ is published.
    """
    # TODO: Build the correct FHIR Parameters resource per IG when payload spec is published.
    # For now this is scaffolded only and will raise NotImplementedError to make it obvious.
    raise NotImplementedError(
        "$report-data payload is not yet specified in CMS ACCESS IG v0.9.1. "
        "Implement once IG v0.9.6+ is published."
    )


def poll_submission_status(secrets: dict, status_url: str) -> dict:
    """GET a submission-status URL returned in a Content-Location header."""
    token = get_access_token(secrets)
    http = Http()
    http.headers = {"Authorization": f"Bearer {token}"}
    response = http.get(status_url)
    response.raise_for_status()
    return response.json()
