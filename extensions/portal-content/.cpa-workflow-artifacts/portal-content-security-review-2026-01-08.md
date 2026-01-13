# Security Review: portal_content

**Date:** 2026-01-08
**Reviewer:** Claude Code
**Plugin Version:** 0.0.1
**Status:** PASS

---

## Executive Summary

The `portal_content` plugin implements a patient portal with educational materials, imaging reports, lab reports, and visit notes. This security review confirms the plugin follows Canvas SDK best practices for authentication and authorization.

**Key Security Improvements Since Last Review:**
- Refactored to use `PatientSessionAuthMixin` instead of manual `authenticate()` method
- Authentication is now handled by SDK-provided security mechanisms

---

## Plugin API Server Security

### Authentication Implementation

| Check | Status | Notes |
|-------|--------|-------|
| Uses authentication mixin | ✅ PASS | `PatientSessionAuthMixin` used in `PortalContentAPI` |
| No manual `authenticate()` | ✅ PASS | Removed manual implementation, using SDK mixin |
| Patient-only access enforced | ✅ PASS | Mixin ensures only Patient users can access |
| Staff users rejected | ✅ PASS | Mixin raises `InvalidCredentialsError` for non-patients |

**Implementation (portal_api.py:35):**
```python
class PortalContentAPI(PatientSessionAuthMixin, SimpleAPI):
    """API handler for all patient portal content types.

    Uses PatientSessionAuthMixin to ensure only logged-in patients can access endpoints.
    """
```

### Configuration Validation

| Check | Status | Notes |
|-------|--------|-------|
| Config validated before processing | ✅ PASS | `_validate_config()` called at start of each endpoint |
| Missing credentials rejected | ✅ PASS | Returns 500 if CLIENT_ID/CLIENT_SECRET missing |
| Visits requires NOTE_TYPES | ✅ PASS | Validation enforces NOTE_TYPES when visits enabled |

---

## FHIR Client Security

### Token Management

| Check | Status | Notes |
|-------|--------|-------|
| Credentials in secrets | ✅ PASS | CLIENT_ID, CLIENT_SECRET declared in manifest |
| No hardcoded tokens | ✅ PASS | All tokens obtained via OAuth flow |
| Patient-scoped tokens | ✅ PASS | Token request includes `patient` parameter |
| Minimal scopes requested | ✅ PASS | Only `patient/DiagnosticReport.read patient/DocumentReference.read` |

**Token Request (portal_api.py:76-84):**
```python
response = requests.post(
    f"{token_host}/auth/token/",
    data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "patient": patient_id,  # Patient-scoped!
        "scope": "patient/DiagnosticReport.read patient/DocumentReference.read",
    },
)
```

### Token Leakage Prevention

| Check | Status | Notes |
|-------|--------|-------|
| Tokens not logged | ✅ PASS | Only token length logged, not content |
| Tokens in headers only | ✅ PASS | Authorization header, not URL params |
| Token errors sanitized | ✅ PASS | Generic error messages returned to client |

---

## Patient Data Access Controls

### Document Ownership Verification

All content types verify document ownership before serving:

| Content Type | Verification Location | Status |
|--------------|----------------------|--------|
| Education | `education.py:proxy_pdf()` lines 232-246 | ✅ PASS |
| Imaging | `imaging.py:proxy_pdf()` lines 232-246 | ✅ PASS |
| Labs | `labs.py:proxy_pdf()` lines 232-246 | ✅ PASS |
| Visits | `visits.py:proxy_pdf()` lines 255-269 | ✅ PASS |

**Verification Pattern:**
```python
# Fetch document metadata
doc_ref = verify_response.json()
subject = doc_ref.get("subject", {})
subject_ref = subject.get("reference", "")
doc_patient_id = subject_ref.replace("Patient/", "")

# Verify ownership
if doc_patient_id != patient_id:
    log.error(f"SECURITY: Patient {patient_id} attempted to access document belonging to {doc_patient_id}")
    return [JSONResponse({"status": "error", "message": "Access denied"}, status_code=HTTPStatus.FORBIDDEN)]
```

### Visit Notes Security

| Check | Status | Notes |
|-------|--------|-------|
| Patient ownership verified | ✅ PASS | Note.patient.id checked against requesting patient |
| Only finalized notes shown | ✅ PASS | FINALIZED_STATES = ["SGN", "LKD", "RLK", "DSC"] |
| Non-finalized notes rejected | ✅ PASS | Returns 403 Forbidden |

---

## Application Scope Alignment

All applications are correctly scoped for patient portal:

| Application | Manifest Scope | Status |
|-------------|---------------|--------|
| EducationMaterialsApp | `portal_menu_item` | ✅ Correct |
| ImagingReportsApp | `portal_menu_item` | ✅ Correct |
| LabReportsApp | `portal_menu_item` | ✅ Correct |
| VisitNotesApp | `portal_menu_item` | ✅ Correct |

---

## Secrets Declaration

All required secrets properly declared in CANVAS_MANIFEST.json:

| Secret | Purpose | Declared |
|--------|---------|----------|
| `ENABLED_COMPONENTS` | Feature flags | ✅ Yes |
| `CLIENT_ID` | OAuth client ID | ✅ Yes |
| `CLIENT_SECRET` | OAuth client secret | ✅ Yes |
| `NOTE_TYPES` | Visit note type filter | ✅ Yes |

---

## Security Audit Summary

### Handlers Reviewed

| Handler Type | Count | Authentication |
|--------------|-------|----------------|
| SimpleAPI (PortalContentAPI) | 1 | PatientSessionAuthMixin |
| Application | 4 | Component-enabled check |

### Endpoints Reviewed

| Endpoint | Method | Auth | Patient Scope |
|----------|--------|------|---------------|
| `/education/portal` | GET | ✅ | ✅ |
| `/education/reports` | POST | ✅ | ✅ |
| `/education/pdf` | GET | ✅ | ✅ |
| `/imaging/portal` | GET | ✅ | ✅ |
| `/imaging/reports` | POST | ✅ | ✅ |
| `/imaging/pdf` | GET | ✅ | ✅ |
| `/labs/portal` | GET | ✅ | ✅ |
| `/labs/reports` | POST | ✅ | ✅ |
| `/labs/pdf` | GET | ✅ | ✅ |
| `/visits/portal` | GET | ✅ | ✅ |
| `/visits/notes` | POST | ✅ | ✅ |
| `/visits/pdf` | GET | ✅ | ✅ |

---

## Findings

| Severity | Issue | Location | Status |
|----------|-------|----------|--------|
| - | None | - | All checks passed |

---

## Recommendations

1. **Implemented:** Using `PatientSessionAuthMixin` for authentication (completed this session)
2. **Consider:** Adding rate limiting for PDF proxy endpoints (not critical, Canvas may handle this)
3. **Consider:** Adding audit logging for document access (optional enhancement)

---

## Conclusion

**PASS** - The portal_content plugin implements proper security controls:

- ✅ Uses SDK authentication mixin (PatientSessionAuthMixin)
- ✅ Patient-scoped FHIR tokens with minimal scopes
- ✅ Document ownership verification before serving
- ✅ Visit notes restricted to finalized states
- ✅ No hardcoded credentials
- ✅ No token leakage in logs

The plugin is approved for deployment.
