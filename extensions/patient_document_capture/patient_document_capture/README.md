# Patient Document Capture

Capture a photo of a document or upload a file directly from the patient chart and
save it to the chart as a native Canvas `DocumentReference`. The patient is
associated automatically from chart context.

## Features

- Launches from the **app drawer** on the patient chart (`patient_specific` scope).
- **Camera capture** (multi-page, with crop/rotate) or **file upload**
  (PDF / JPG / PNG / HEIC), via a portrait modal with a 3:4 viewfinder tuned for
  documents on desktop and iPad. Uploaded images are normalized (EXIF orientation
  corrected, HEIC converted to JPEG) in the browser.
- **Page management** before saving: reorder pages by drag, tap to preview (images and
  multi-page PDFs), and delete individual pages.
- All captured/uploaded pages are combined **in the browser** into a single PDF
  (using `pdf-lib`) — no server-side PDF libraries are required.
- Requires a **document type** (Clinical or Administrative), a **title**, and a valid
  **document date** (YYYY-MM-DD, defaults to today, may not be in the future) before saving.
- **Idempotent save**: a per-document key (reused on retry) prevents duplicate
  `DocumentReference` records if a save is retried, with a determinate upload progress bar.
- Saves as a `DocumentReference` via the Canvas FHIR API with the PDF embedded inline
  (base64) — no external S3 or cloud storage.

## How it works

1. The `PatientDocumentCaptureApp` Application renders the capture modal, injecting the
   current `patient_id`.
2. The modal collects pages (camera frames as JPEG, or uploaded PDF/JPG/PNG), assembles
   them into one PDF with `pdf-lib`, and POSTs it as `multipart/form-data` to
   `/plugin-io/api/patient_document_capture/documents/submit`.
3. `DocumentAPI` (`StaffSessionAuthMixin` + `SimpleAPI`) validates the request, then
   `document_fhir.create_document_reference` creates the `DocumentReference` via the
   Canvas FHIR client.

## Document types

| UI choice      | LOINC type | Display                                 | Category code                    |
|----------------|------------|-----------------------------------------|----------------------------------|
| Clinical       | `34109-9`  | Uncategorized Clinical Document         | `uncategorizedclinicaldocument`  |
| Administrative | `51851-4`  | Uncategorized Administrative Document   | `patientadministrativedocument`  |

The provider picks the type; the FHIR `category` is derived automatically. The title is
saved to the document's `description` (and `content.attachment.title`).

## Components

- `applications/document_app.py` — `PatientDocumentCaptureApp` (app drawer entry).
- `api/document_api.py` — `DocumentAPI` SimpleAPI endpoint (`POST /documents/submit`).
- `services/document_fhir.py` — builds the payload and creates the `DocumentReference`.
- `utils/constants.py` — document type → LOINC/category mapping, limits, secret keys.
- `templates/upload_modal.html` — self-contained capture/upload modal UI.

## Secrets

| Secret | Purpose |
|--------|---------|
| `CANVAS_FHIR_CLIENT_ID` | OAuth client id for the Canvas FHIR API (write `DocumentReference`). |
| `CANVAS_FHIR_CLIENT_SECRET` | Corresponding OAuth client secret. |

Create a Canvas API application with permission to write `DocumentReference` resources
and set these as plugin secrets.

## Limits

- Up to 20 pages per document.
- Combined PDF capped at 10 MB (checked client-side before upload and enforced
  server-side via `MAX_PDF_BYTES`).
- Title capped at 255 characters; sanitized to a single line.
- Document date must be a real date no later than today.
