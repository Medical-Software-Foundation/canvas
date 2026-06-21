"""Thin wrapper around the CMS ACCESS FHIR API operations.

URL structure (per Operations Manual v0.9.11):
    <ACCESS_BASE_URL>/access/<resourceType>/<operation>?entityId=<entityId>

Real example:
    https://impl-cdxapi.cmmi.cms.gov/cdx/services/fhir/access/Patient/$check-eligibility?entityId=ACCES12345

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

# Systems for identifier / codeable-concept parameters (per OM v0.9.11).
_PARTICIPANT_ID_SYSTEM = "https://dsacms.github.io/cmmi-access-model/participant-id"
_PAYER_ID_OID_SYSTEM = "urn:oid:2.16.840.1.113883.3.221.5"
_PAYER_ID_TYPE_SYSTEM = "http://hl7.org/fhir/us/carin-bb/CodeSystem/C4BBIdentifierType"
_TRACK_CS_SYSTEM = "https://dsacms.github.io/cmmi-access-model/CodeSystem/ACCESSTrackCS"
_UNALIGN_REASON_CS_SYSTEM = (
    "https://dsacms.github.io/cmmi-access-model/CodeSystem/ACCESSUnalignmentReasonCS"
)
_MBI_SYSTEM = "http://terminology.hl7.org/NamingSystem/cmsMBI"
_V2_0203_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"

# Operation input Parameters profiles. The IMPL server rejects payloads without
# meta.profile ("missing required field(s): meta.profile"), so every operation's
# Parameters resource must declare its access-*-in profile.
_SD_BASE = "https://dsacms.github.io/cmmi-access-model/StructureDefinition"
_CHECK_ELIGIBILITY_IN_PROFILE = f"{_SD_BASE}/access-check-eligibility-in"
_ALIGN_IN_PROFILE = f"{_SD_BASE}/access-align-in"
_UNALIGN_IN_PROFILE = f"{_SD_BASE}/access-unalign-in"
_REPORT_DATA_IN_PROFILE = f"{_SD_BASE}/access-report-data-in"

# reportType CodeSystem (OM v0.9.11 $report-data).
_REPORT_TYPE_CS_SYSTEM = "https://dsacms.github.io/cmmi-access-model/CodeSystem/ACCESSReportTypeCS"
_REPORT_TYPE_DISPLAY = {
    "baseline": "Baseline Data Report",
    "quarterly": "Quarterly Data Report",
    "end-of-period": "End-of-Period Data Report",
}

# Track code → display name (per OM v0.9.11 examples and track description sections).
_TRACK_DISPLAY = {
    "eCKM": "Early Cardio-Kidney-Metabolic track",
    "CKM": "Cardio-Kidney-Metabolic track",
    "MSK": "Musculoskeletal track",
    "BH": "Behavioral Health track",
}


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
        # The Operations Manual v0.9.11 specifies request Content-Type application/json.
        "Content-Type": "application/json",
        "Prefer": _PREFER_ASYNC,
    }
    return http, headers


def _parse_operation_outcome(body: dict) -> str:
    """Extract the first issue detail text from a FHIR OperationOutcome body."""
    issues = body.get("issue", [])
    if issues:
        return issues[0].get("details", {}).get("text", "Unknown error")
    return "Unknown error"


def _redact_headers(headers: dict) -> dict:
    """Copy headers, masking the bearer token so it never reaches the UI/logs.

    We still surface that an Authorization header was sent (and its length) so a
    missing/empty token is obvious when troubleshooting, without exposing the JWT.
    """
    redacted = {}
    for key, value in headers.items():
        if key.lower() == "authorization":
            token = value[len("Bearer ") :] if value.startswith("Bearer ") else value
            redacted[key] = f"Bearer <redacted, {len(token)} chars>"
        else:
            redacted[key] = value
    return redacted


def _response_body(response) -> dict | str | None:
    """Return the response body as parsed JSON, falling back to raw text."""
    text = response.text or ""
    if not text:
        return None
    try:
        return response.json()
    except ValueError:
        return text


def _build_exchange(
    method: str,
    full_url: str,
    headers: dict,
    response,
    request_body: dict | None = None,
    query_params: dict | None = None,
) -> dict:
    """Capture a full request/response HTTP exchange for the inspector UI.

    Returns a JSON-serializable dict with everything needed to troubleshoot a CMS
    call: method, URL, request headers (token redacted), query params, request body,
    and the response status, headers, Content-Location, and body.
    """
    return {
        "request": {
            "method": method,
            "url": full_url,
            "headers": _redact_headers(headers),
            "query_params": query_params or {},
            "body": request_body,
        },
        "response": {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content_location": response.headers.get("Content-Location"),
            "body": _response_body(response),
        },
    }


def _full_url(base_url: str, rel_url: str) -> str:
    """Join the (possibly slash-less) base URL with an operation's relative path."""
    return base_url.rstrip("/") + "/" + rel_url.lstrip("/")


def _operation_url(operation: str, participant_id: str) -> str:
    """Build the operation URL relative to the (slash-terminated) base URL."""
    return f"{_MODEL_ID}/Patient/${operation}?entityId={quote(participant_id)}"


def _participant_id_param(value: str) -> dict:
    """Build the participantID parameter with valueIdentifier shape (OM v0.9.11)."""
    return {
        "name": "participantID",
        "valueIdentifier": {
            "system": _PARTICIPANT_ID_SYSTEM,
            "value": value,
        },
    }


def _payer_id_param(value: str) -> dict:
    """Build the payerID parameter with valueIdentifier + CARIN BB type coding (OM v0.9.11)."""
    return {
        "name": "payerID",
        "valueIdentifier": {
            "type": {
                "coding": [
                    {
                        "system": _PAYER_ID_TYPE_SYSTEM,
                        "code": "payerid",
                        "display": "Payer ID",
                    }
                ]
            },
            "system": _PAYER_ID_OID_SYSTEM,
            "value": value,
        },
    }


def _track_param(code: str) -> dict:
    """Build the track parameter with valueCodeableConcept shape (OM v0.9.11)."""
    display = _TRACK_DISPLAY.get(code, code)
    return {
        "name": "track",
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": _TRACK_CS_SYSTEM,
                    "code": code,
                    "display": display,
                }
            ]
        },
    }


def _report_type_param(code: str) -> dict:
    """Build the reportType parameter with valueCodeableConcept shape (OM v0.9.11)."""
    return {
        "name": "reportType",
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": _REPORT_TYPE_CS_SYSTEM,
                    "code": code,
                    "display": _REPORT_TYPE_DISPLAY.get(code, code),
                }
            ]
        },
    }


def _unalign_reason_param(code: str) -> dict:
    """Build the reason parameter with valueCodeableConcept shape (OM v0.9.11)."""
    return {
        "name": "reason",
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": _UNALIGN_REASON_CS_SYSTEM,
                    "code": code,
                }
            ]
        },
    }


def check_eligibility(
    secrets: dict,
    patient_resource: dict,
    payer_id: str,
    track: str,
    conditions: list[dict] | None = None,
    debug: list | None = None,
) -> tuple[int, str | None, dict]:
    """POST $check-eligibility. Returns (status_code, content_location_url, body_dict).

    Payload shape per Operations Manual v0.9.11 §$check-eligibility:
    - participantID: valueIdentifier
    - payerID: valueIdentifier (CARIN BB typed)
    - patient: embedded Patient resource containing cmsMBI identifier + name + gender + birthDate
    - track: valueCodeableConcept (ACCESSTrackCS)

    Per OM v0.9.11, all four operations are async — a successful POST returns 202
    with an empty body and a Content-Location pointing at the submission-status
    URL. The eligibility result itself comes back via the poller.

    On 400, raises RuntimeError with the OperationOutcome detail text.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "meta": {"profile": [_CHECK_ELIGIBILITY_IN_PROFILE]},
        "parameter": [
            _participant_id_param(participant_id),
            _payer_id_param(payer_id),
            {"name": "patient", "resource": patient_resource},
            _track_param(track),
            # condition (0..*) — optional; lets CMS confirm eligibility against a
            # qualifying diagnosis (otherwise it may return eligible-pending-diagnosis).
            *[{"name": "condition", "resource": c} for c in (conditions or [])],
        ],
    }
    rel_url = _operation_url("check-eligibility", participant_id)
    response = http.post(rel_url, json=payload, headers=headers)

    if debug is not None:
        debug.append(
            _build_exchange(
                "POST",
                _full_url(secrets["ACCESS_BASE_URL"], rel_url),
                headers,
                response,
                request_body=payload,
                query_params={"entityId": participant_id},
            )
        )

    if response.status_code == 400:
        detail = _parse_operation_outcome(response.json())
        raise RuntimeError(f"$check-eligibility pre-validation failed: {detail}")

    if not response.ok:
        raise RuntimeError(
            f"$check-eligibility failed: HTTP {response.status_code} {response.text[:200]}"
        )
    content_location = response.headers.get("Content-Location")
    body = response.json() if response.text else {}
    return response.status_code, content_location, body


def align(
    secrets: dict,
    patient_resource: dict,
    payer_id: str,
    track: str,
    conditions: list[dict],
    switch_consent: bool = False,
    debug: list | None = None,
) -> tuple[int, str | None, dict]:
    """POST $align. Returns (status_code, content_location_url, body_dict).

    Payload shape per Operations Manual v0.9.11 §Alignment API:
    - participantID: valueIdentifier
    - payerID: valueIdentifier (CARIN BB typed)
    - patient: embedded Patient resource
    - track: valueCodeableConcept (ACCESSTrackCS)
    - condition: one or more embedded Condition resources (REQUIRED, 1..*) whose code
      is drawn from the track-specific diagnosis value set
    - isProviderReferral: valueBoolean (false — no referral source collected in UI yet)

    ``conditions`` must be non-empty; CMS rejects $align without at least one
    track-qualifying condition (the caller is responsible for failing closed when the
    patient has no qualifying diagnosis). ``clinicalJustification`` is no longer sent —
    it is not a parameter in the v0.9.11 OperationDefinition; the plugin keeps it on the
    ACCESSAlignment row for internal documentation only.

    202 means async — caller should store content_location_url and poll.
    On 400, raises RuntimeError with the OperationOutcome detail text.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")
    if not conditions:
        raise ValueError("$align requires at least one track-qualifying condition")

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "meta": {"profile": [_ALIGN_IN_PROFILE]},
        "parameter": [
            _participant_id_param(participant_id),
            _payer_id_param(payer_id),
            {"name": "patient", "resource": patient_resource},
            _track_param(track),
            *[{"name": "condition", "resource": condition} for condition in conditions],
            {"name": "isProviderReferral", "valueBoolean": False},
            # switchConsentAttestation (0..1) — only sent when the provider attests the
            # patient consented to switch from another ACCESS participant (OM v0.9.12).
            *([{"name": "switchConsentAttestation", "valueBoolean": True}] if switch_consent else []),
        ],
    }
    rel_url = _operation_url("align", participant_id)
    response = http.post(rel_url, json=payload, headers=headers)

    if debug is not None:
        debug.append(
            _build_exchange(
                "POST",
                _full_url(secrets["ACCESS_BASE_URL"], rel_url),
                headers,
                response,
                request_body=payload,
                query_params={"entityId": participant_id},
            )
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
    patient_resource: dict,
    payer_id: str,
    track: str,
    reason_code: str,
    conditions: list[dict] | None = None,
    debug: list | None = None,
) -> tuple[int, str | None, dict]:
    """POST $unalign. Returns (status_code, content_location_url, body_dict).

    Payload shape per Operations Manual v0.9.11 §$unalign:
    - participantID: valueIdentifier
    - payerID: valueIdentifier (CARIN BB typed)
    - patient: embedded Patient resource
    - track: valueCodeableConcept (ACCESSTrackCS)
    - reason: valueCodeableConcept (ACCESSUnalignmentReasonCS)
    - condition: one or more embedded Condition resources. REQUIRED when reason is
      ``no-longer-clinically-eligible`` (invariant access-unalign-condition-required),
      documenting the disqualifying diagnosis; otherwise omitted.

    NOTE: The OM does not include an `alignmentId` parameter. The previous
    flat-payload version included alignmentId — that has been removed to match
    the canonical schema. alignmentId is retained on the ACCESSAlignment model
    for internal reference only.

    On 400, raises RuntimeError with the OperationOutcome detail text.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")
    if reason_code == "no-longer-clinically-eligible" and not conditions:
        raise ValueError(
            "$unalign with reason 'no-longer-clinically-eligible' requires at least "
            "one disqualifying condition"
        )

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "meta": {"profile": [_UNALIGN_IN_PROFILE]},
        "parameter": [
            _participant_id_param(participant_id),
            _payer_id_param(payer_id),
            {"name": "patient", "resource": patient_resource},
            _track_param(track),
            _unalign_reason_param(reason_code),
            *[{"name": "condition", "resource": condition} for condition in (conditions or [])],
        ],
    }
    rel_url = _operation_url("unalign", participant_id)
    response = http.post(rel_url, json=payload, headers=headers)

    if debug is not None:
        debug.append(
            _build_exchange(
                "POST",
                _full_url(secrets["ACCESS_BASE_URL"], rel_url),
                headers,
                response,
                request_body=payload,
                query_params={"entityId": participant_id},
            )
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


def report_data(
    secrets: dict,
    *,
    payer_id: str,
    track: str,
    report_type: str,
    data_bundle: dict,
    debug: list | None = None,
) -> tuple[int, str | None, dict]:
    """POST $report-data. Returns (status_code, content_location_url, body_dict).

    Payload shape per Operations Manual v0.9.11 §Data Reporting:
    - participantID: valueIdentifier
    - payerID: valueIdentifier (CARIN BB typed)
    - track: valueCodeableConcept (ACCESSTrackCS)
    - reportType: valueCodeableConcept (ACCESSReportTypeCS: baseline/quarterly/end-of-period)
    - dataBundle: an ACCESSDataReportingBundle (document Bundle); the Patient is embedded
      INSIDE the bundle (not a separate top-level parameter)

    ``data_bundle`` is built by ``report_data.build_data_bundle``. Async: 202 means the
    caller should store content_location and poll. On 400, raises RuntimeError with the
    OperationOutcome detail.
    """
    participant_id = secrets.get("ACCESS_PARTICIPANT_ID")
    if not participant_id:
        raise ValueError("Missing required secret: ACCESS_PARTICIPANT_ID")

    http, headers = _build_http(secrets)
    payload = {
        "resourceType": "Parameters",
        "meta": {"profile": [_REPORT_DATA_IN_PROFILE]},
        "parameter": [
            _participant_id_param(participant_id),
            _payer_id_param(payer_id),
            _track_param(track),
            _report_type_param(report_type),
            {"name": "dataBundle", "resource": data_bundle},
        ],
    }
    rel_url = _operation_url("report-data", participant_id)
    response = http.post(rel_url, json=payload, headers=headers)

    if debug is not None:
        debug.append(
            _build_exchange(
                "POST",
                _full_url(secrets["ACCESS_BASE_URL"], rel_url),
                headers,
                response,
                request_body=payload,
                query_params={"entityId": participant_id},
            )
        )

    if response.status_code == 400:
        detail = _parse_operation_outcome(response.json())
        raise RuntimeError(f"$report-data pre-validation failed: {detail}")

    if not response.ok:
        raise RuntimeError(
            f"$report-data failed: HTTP {response.status_code} {response.text[:200]}"
        )
    content_location = response.headers.get("Content-Location")
    body = response.json() if response.text else {}
    return response.status_code, content_location, body


def poll_submission_status(
    secrets: dict, status_url: str, debug: list | None = None
) -> tuple[int, dict]:
    """GET a submission-status URL returned in a Content-Location header.

    Returns (status_code, body_dict).

    Error handling follows the OM v0.9.11 polling guidance:
      202        → still processing (keep polling)
      200        → complete (result CodeableConcept / OperationOutcome body)
      4xx        → terminal client error (e.g. 404 submission-not-found) — RETURNED to the
                   caller (not raised) so it can stop polling and surface the result.
      5xx / net  → transient — raised as RuntimeError so the caller backs off and retries.
    """
    token = get_access_token(secrets)
    http = Http()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = http.get(status_url, headers=headers)
    except Exception as exc:  # noqa: BLE001 - network failure is transient per OM; retry
        raise RuntimeError(f"$submission-status network error: {exc}")

    if debug is not None:
        debug.append(_build_exchange("GET", status_url, headers, response))

    # 5xx is a transient server error per OM → signal the caller to retry with backoff.
    if response.status_code >= 500:
        raise RuntimeError(
            f"$submission-status transient error: HTTP {response.status_code} {response.text[:200]}"
        )

    # 200/202 and terminal 4xx are returned for the caller to branch on.
    body = response.json() if response.text else {}
    return response.status_code, body
