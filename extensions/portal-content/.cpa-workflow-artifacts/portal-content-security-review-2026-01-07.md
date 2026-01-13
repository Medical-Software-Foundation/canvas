# Security Review: portal_content

**Date:** 2026-01-07
**Plugin:** portal_content
**Version:** 0.0.1

## Plugin API Server Security Review

### Authentication Analysis

The plugin uses a **manual `authenticate()` method** in `PortalContentAPI` (SimpleAPI handler):

```python
def authenticate(self, credentials: SessionCredentials) -> bool:
    # Validates configuration
    # Checks logged_in_user exists
    # Verifies user type is "Patient"
    return True
```

**Assessment:**
- **Patient-only enforcement:** Correctly validates `user.get("type") == "Patient"`
- **Null check:** Properly checks `if not user: return False`
- **Logging:** Auth failures are logged with warnings

**Recommendation:** Consider using `PatientSessionMixin` for cleaner code, but current implementation is secure.

### Endpoint Security Summary

| Endpoint | Method | Auth | Assessment |
|----------|--------|------|------------|
| `/education/portal` | GET | Patient session | Secure |
| `/education/reports` | POST | Patient session | Secure |
| `/education/pdf` | GET | Patient session | Secure |
| `/imaging/portal` | GET | Patient session | Secure |
| `/imaging/reports` | POST | Patient session | Secure |
| `/imaging/pdf` | GET | Patient session | Secure |
| `/labs/portal` | GET | Patient session | Secure |
| `/labs/reports` | POST | Patient session | Secure |
| `/labs/pdf` | GET | Patient session | Secure |
| `/visits/portal` | GET | Patient session | Secure |
| `/visits/notes` | POST | Patient session | Secure |
| `/visits/pdf` | GET | Patient session | Secure |

All endpoints require patient authentication.

---

## FHIR API Client Security Review

### Token Management

The plugin uses OAuth 2.0 client credentials flow with **patient-scoped tokens**.

**Token Request (`_get_fhir_token`):**
```python
response = requests.post(
    f"{token_host}/auth/token/",
    data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "patient": patient_id,  # Patient-scoped
        "scope": "patient/DiagnosticReport.read patient/DocumentReference.read",
    },
)
```

### Scope Analysis

| Requested Scope | Purpose | Assessment |
|-----------------|---------|------------|
| `patient/DiagnosticReport.read` | Read lab/imaging reports | Appropriate - minimum needed |
| `patient/DocumentReference.read` | Read documents | Appropriate - minimum needed |

**Assessment:** Scopes follow principle of least privilege.

### Patient-Scoped Token Compliance

| Check | Status | Notes |
|-------|--------|-------|
| Manifest scope is `portal_menu_item` | Pass | All 4 applications are patient portal items |
| Token includes `patient` parameter | Pass | `"patient": patient_id` in token request |
| Patient ID from authenticated session | Pass | Uses `credentials.logged_in_user.get("id")` |

### Token Security Checks

| Check | Status | Notes |
|-------|--------|-------|
| Tokens from secrets | Pass | `self.secrets.get("CLIENT_ID")`, `self.secrets.get("CLIENT_SECRET")` |
| Secrets declared in manifest | Pass | `CLIENT_ID`, `CLIENT_SECRET` in secrets array |
| No hardcoded tokens | Pass | No hardcoded tokens found |
| Token existence validated | Pass | Checks `if not client_id or not client_secret` |
| Token not logged | Pass | Only logs token length, not token value |

**Token Logging (line 98):**
```python
log.info(f"Successfully retrieved FHIR token (length: {len(token)})")
```
This is acceptable - logs length for debugging but not the actual token.

---

## Findings Summary

| Severity | Issue | Location | Status |
|----------|-------|----------|--------|
| - | - | - | No issues found |

## Overall Assessment

### Plugin API Server Security: **PASS**
- Patient-only authentication correctly enforced
- All endpoints protected by session authentication
- Auth failures properly logged

### FHIR Client Security: **PASS**
- Patient-scoped tokens used correctly for portal_menu_item apps
- Minimum necessary scopes requested
- Secrets properly managed and validated
- No token leakage in logs

---

**Verdict: PASS - No security issues found**
