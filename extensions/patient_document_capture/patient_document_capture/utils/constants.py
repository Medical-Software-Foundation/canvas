"""Shared constants for the patient_document_capture plugin."""

PLUGIN_NAME = "patient_document_capture"

# Secret keys (declared in CANVAS_MANIFEST.json)
SECRET_FHIR_CLIENT_ID = "CANVAS_FHIR_CLIENT_ID"
SECRET_FHIR_CLIENT_SECRET = "CANVAS_FHIR_CLIENT_SECRET"

# FHIR coding systems
LOINC_SYSTEM = "http://loinc.org"
CATEGORY_SYSTEM = "http://schemas.canvasmedical.com/fhir/document-reference-category"

# Required Canvas extensions on DocumentReference create.
CLINICAL_DATE_EXTENSION = (
    "http://schemas.canvasmedical.com/fhir/document-reference-clinical-date"
)
REVIEWER_EXTENSION = (
    "http://schemas.canvasmedical.com/fhir/document-reference-reviewer"
)
REQUIRES_SIGNATURE_EXTENSION = (
    "http://schemas.canvasmedical.com/fhir/document-reference-requires-signature"
)
REVIEW_MODE_EXTENSION = (
    "http://schemas.canvasmedical.com/fhir/document-reference-review-mode"
)
# Review Mode values: RR (Review Required), AR (Already Reviewed), RN (Review Not Required).
REVIEW_MODE_NOT_REQUIRED = "RN"

# Document type choices presented in the UI. The provider picks one; the category
# is derived automatically. Each entry maps a UI key to its LOINC type code/display
# and the Canvas DocumentReference category code.
#
# Build-time note: confirm against the fumage DocumentReference create mapping that
# these two type/category codes are settable on create.
DOCUMENT_TYPES = {
    "clinical": {
        "loinc_code": "34109-9",
        "loinc_display": "Uncategorized Clinical Document",
        "category_code": "uncategorizedclinicaldocument",
    },
    "administrative": {
        "loinc_code": "51851-4",
        "loinc_display": "Uncategorized Administrative Document",
        "category_code": "patientadministrativedocument",
    },
}

# The browser assembles all captured/uploaded pages into a single PDF (via pdf-lib)
# and posts that one file. The backend only ever receives a finished PDF.
PDF_CONTENT_TYPE = "application/pdf"

# Accepted page input types in the browser UI (used for the file picker / drop zone).
# Camera captures are produced as JPEG by the modal. HEIC is intentionally excluded
# because pdf-lib can embed JPEG/PNG but not HEIC.
UI_ACCEPTED_CONTENT_TYPES = ("application/pdf", "image/jpeg", "image/png")

# Guard against oversized payloads (the single combined PDF). Inline base64 inflates
# this ~33% on the wire to fumage, so keep a conservative cap until the real ceiling
# is confirmed on-instance. Mirrored client-side for a pre-upload check.
MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB

# Idempotency: cache the created DocumentReference id per client-supplied key so a
# retry (after a timeout where the create actually succeeded) returns the same id
# instead of creating a duplicate. Short TTL is enough to cover a retry window.
IDEMPOTENCY_CACHE_PREFIX = "pdc:idem:"
IDEMPOTENCY_TTL_SECONDS = 60 * 60  # 1 hour

# The title maps to a single-line field on the Canvas document. Collapse whitespace
# and cap length defensively so it can never break the DocumentReference create.
MAX_TITLE_LENGTH = 255

# fumage requires a strictly zero-padded YYYY-MM-DD clinical date.
CLINICAL_DATE_FORMAT = "%Y-%m-%d"
