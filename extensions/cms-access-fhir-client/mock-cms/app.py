"""Mock CMS ACCESS FHIR server for end-to-end testing of cms-access-fhir-client.

Mimics the four CMS operations and the OAuth token endpoint just enough for the
plugin's outbound flow to complete successfully against this server.

Changes from the original mock to match real CMS behaviour:
- OAuth: accepts HTTP Basic auth (Authorization: Basic ...) instead of form fields.
  Still accepts any credentials — just validates the header format.
- Endpoints: moved to /access/Patient/... per the real URL structure.
  entityId is read from the query-string.
- Submission polling: returns HTTP 202 + empty body + X-Progress header for
  in-progress, HTTP 200 + Parameters body for completed.
- New error branch: pass ?force_error=true on the submission GET URL to have
  the mock return 200 + OperationOutcome (tests the error-parsing path).

Run:
    uv run uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Expose to allison-training (pick one):
    cloudflared tunnel --url http://localhost:8000
    ngrok http 8000
"""
from __future__ import annotations

import base64
import uuid
from typing import Annotated

from fastapi import FastAPI, Form, Header, HTTPException, Query, Request, Response

app = FastAPI(title="Mock CMS ACCESS")

# In-memory submission tracking. Polled GETs advance state until "completed".
SUBMISSIONS: dict[str, dict] = {}
POLLS_BEFORE_COMPLETE = 1  # first GET → in-progress, second GET → completed


@app.post("/oauth/token")
def oauth_token(
    request: Request,
    grant_type: Annotated[str, Form()],
    scope: Annotated[str | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """OAuth 2.0 client_credentials with HTTP Basic auth.

    CMS requires credentials in the Authorization: Basic ... header.
    This mock validates that the header is present and base64-decodable,
    then accepts any decoded credentials.
    """
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Authorization: Basic <base64(client_id:client_secret)> header required",
        )
    encoded = authorization[len("Basic "):]
    try:
        decoded = base64.b64decode(encoded).decode()
        if ":" not in decoded:
            raise ValueError("missing colon separator")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Basic auth encoding")

    return {
        "access_token": "fake-" + uuid.uuid4().hex[:12],
        "expires_in": 300,  # 5 min — matches real CMS
        "token_type": "Bearer",
        "scope": scope or "cdx/*.read cdx/fhir-resource.write",
    }


@app.post("/access/Patient/$check-eligibility")
async def check_eligibility(
    request: Request,
    entity_id: Annotated[str | None, Query(alias="entityId")] = None,
) -> dict:
    """Synchronous check-eligibility. Returns FHIR Parameters with status=eligible."""
    body = await request.json()
    patient_ref = _extract_param(body, "patient", "valueReference") or {
        "reference": "Patient/unknown"
    }
    return {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "status", "valueCode": "eligible"},
            {"name": "patient", "valueReference": patient_ref},
            {"name": "eligibleTracks", "valueString": "eCKM,CKM,MSK,BH"},
        ],
    }


@app.post("/access/Patient/$align")
async def align(
    request: Request,
    entity_id: Annotated[str | None, Query(alias="entityId")] = None,
) -> Response:
    """Async align. Returns 202 + Content-Location pointing at a submission URL."""
    body = await request.json()
    sub_id = uuid.uuid4().hex
    SUBMISSIONS[sub_id] = {
        "op": "align",
        "alignment_id": "ALIGN-" + uuid.uuid4().hex[:8].upper(),
        "poll_count": 0,
        "request": body,
    }
    base = str(request.base_url).rstrip("/")
    return Response(
        status_code=202,
        headers={"Content-Location": f"{base}/submission/{sub_id}"},
    )


@app.post("/access/Patient/$unalign")
async def unalign(
    request: Request,
    entity_id: Annotated[str | None, Query(alias="entityId")] = None,
) -> Response:
    """Async unalign. Returns 202 + Content-Location."""
    body = await request.json()
    sub_id = uuid.uuid4().hex
    SUBMISSIONS[sub_id] = {
        "op": "unalign",
        "alignment_id": _extract_param(body, "alignmentId", "valueString") or "",
        "poll_count": 0,
        "request": body,
    }
    base = str(request.base_url).rstrip("/")
    return Response(
        status_code=202,
        headers={"Content-Location": f"{base}/submission/{sub_id}"},
    )


@app.get("/submission/{sub_id}")
def submission_status(
    sub_id: str,
    force_error: Annotated[bool, Query(alias="force_error")] = False,
) -> Response:
    """Return submission status.

    - First POLLS_BEFORE_COMPLETE polls: HTTP 202, empty body, X-Progress header
    - After that (or if ?force_error=true): HTTP 200 + body
      - ?force_error=true  → 200 + OperationOutcome (tests error parsing)
      - normal completion  → 200 + Parameters
    """
    sub = SUBMISSIONS.get(sub_id)
    if not sub:
        raise HTTPException(404, "submission not found")

    sub["poll_count"] += 1

    if not force_error and sub["poll_count"] <= POLLS_BEFORE_COMPLETE:
        # Still processing: 202 + empty body + X-Progress header
        return Response(
            status_code=202,
            headers={"X-Progress": "FHIR processing in progress"},
            content="",
        )

    if force_error:
        import json
        body = {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "invalid",
                    "details": {"text": "Mock forced OperationOutcome error"},
                }
            ],
        }
        return Response(
            status_code=200,
            media_type="application/fhir+json",
            content=json.dumps(body),
        )

    if sub["op"] == "align":
        import json
        body = {
            "resourceType": "Parameters",
            "parameter": [
                {"name": "alignmentId", "valueString": sub["alignment_id"]},
                {"name": "careStartDate", "valueDate": "2026-06-01"},
            ],
        }
        return Response(
            status_code=200,
            media_type="application/fhir+json",
            content=json.dumps(body),
        )

    # unalign
    import json
    body = {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "alignmentId", "valueString": sub["alignment_id"]},
        ],
    }
    return Response(
        status_code=200,
        media_type="application/fhir+json",
        content=json.dumps(body),
    )


@app.get("/_state")
def debug_state() -> dict:
    """Inspect in-memory submissions. Useful when poking the mock by hand."""
    return {"submissions": SUBMISSIONS}


def _extract_param(body: dict, name: str, field: str):
    for p in body.get("parameter", []):
        if p.get("name") == name:
            return p.get(field)
    return None
