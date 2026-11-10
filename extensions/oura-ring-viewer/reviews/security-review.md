# Security Review Report: oura_ring_viewer

**Generated:** 2026-11-02
**Reviewer:** Claude Code, following the Canvas Plugin Assistant `/cpa:security-review`
checklist (canvas-medical/coding-agents, commit 4e90e08)

## Summary

| Category | Status | Issues |
|----------|--------|--------|
| Plugin API Server Security | ✅ Pass | 1 documented exception (public OAuth bridge) |
| FHIR API Client Security | N/A | The plugin calls no Canvas FHIR API |
| Application Scope | ✅ Pass | None |
| Secrets Declaration | ✅ Pass | None |

## Detailed Findings

### Plugin API Server Security

Three SimpleAPI handlers:

| Handler | Authentication | Authorization |
|---|---|---|
| `OuraChartAPI` (`protocols/chart_api.py:129`) | `StaffSessionAuthMixin` | Every route passes `_gate` (`chart_api.py:91`): patient id validated, then the caller is identified from the Canvas-set session headers and checked against `OURA_ACCESS_RULE` (`services/access.py:54`). Default `care_team`: only active members of the patient's care team. Inactive staff never qualify. Refusals return 403 and are logged. |
| `OuraPortalAPI` (`protocols/portal_api.py:52`) | `PatientSessionAuthMixin` | The patient is always the one named by the Canvas session header, never a URL parameter, so a patient can act only on their own connection. No `PORTAL_ACCESS` is declared, so a login acting for someone else (for example a parent) is refused. |
| `OuraOAuthAPI` (`protocols/oauth_api.py:47`) | `authenticate()` returns True | See the exception below. |

**Documented exception: public OAuth bridge.** `/connect` and `/callback` must be
reachable without a Canvas session. The patient opens `/connect` from a link on
their phone, often without being signed in to the portal, and `/callback` is
where Oura's servers redirect the browser. Each handler authenticates the
request itself:

- `/connect` requires an HS256 link token (`services/magic_link.py`): signed with
  `OURA_MAGIC_LINK_SECRET` (at least 32 characters), algorithm pinned so `alg:
  none` is rejected, typed so a state token cannot be replayed as a link, 3 day
  expiry, and bound to a single-use nonce stored for the patient. Only the most
  recently issued link works.
- `/callback` requires a signed OAuth `state` token (typed, 1 hour expiry) carrying
  the same nonce. The nonce is burned on success, so a completed flow cannot be
  replayed.
- Rejections are logged and return a plain page with 400, 401 or 409. No route
  returns token material.

This is the same pattern as Canvas's own `dexcom-cgm-viewer` reference plugin
(`protocols/oauth_api.py`, "handlers validate their own tokens"). Moving the
checks into `authenticate()` would replace the patient-facing explanation of an
expired or replaced link with a bare 401, so they are kept in the handlers.

Other checklist items:

- API key auth: not used, so `compare_digest` does not apply. The link secret is
  checked for presence and length before any signing or verifying.
- Error messages name settings that are missing, never their values.

### FHIR API Client Security

N/A. The plugin makes no calls to Canvas's FHIR API and uses no Canvas token.
Its only outbound calls go to Oura's API (`services/oura_client.py`) with the
patient's own OAuth token, which is loaded server side and never sent to a
browser. Logs record status codes and exception types only, never tokens or
response bodies.

### Application Scope

| Application | Scope | Data it reaches |
|---|---|---|
| `OuraChartApp` | `patient_specific` | Staff routes, gated per patient as above |
| `OuraPortalApp` | `portal_menu_item` | Only the signed-in patient's own connection |

No patient-facing surface uses a staff or global credential.

### Secrets Declaration

Every `self.secrets[...]` read is declared in the manifest `variables` array:
`OURA_CLIENT_ID`, `OURA_CLIENT_SECRET` (sensitive), `OURA_REDIRECT_URI`,
`OURA_ENVIRONMENT`, `OURA_MAGIC_LINK_SECRET` (sensitive), `OURA_ACCESS_RULE`.
No hardcoded tokens or keys: the grep for JWT prefixes and long literals finds none.

## Recommendations

| Priority | Issue | Location | Recommendation |
|----------|-------|----------|----------------|
| LOW | OAuth tokens are stored unencrypted at rest | `services/crypto.py` | The Canvas sandbox blocks `cryptography` (the same documented constraint as `dexcom-cgm-viewer`). `TokenCipher` is the seam for encryption when the platform allows it. Tokens never leave the server. |
| LOW | Disconnect does not revoke the grant at Oura | `protocols/chart_api.py`, `protocols/portal_api.py` | Patients can revoke in their Oura account, as the portal page says. Add revocation once Oura's revoke endpoint is verified. |

## Verdict

**✅ PASS.** No HIGH or MEDIUM issues. One documented, justified exception (the
public OAuth bridge) and two LOW items, both platform or vendor constraints.
