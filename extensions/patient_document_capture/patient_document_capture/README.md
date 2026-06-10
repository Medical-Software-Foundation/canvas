# Patient Document Capture

Capture a photo of a document or upload a file directly from the patient chart and
save it to the chart as a native Canvas `DocumentReference`. The patient is
associated automatically from chart context.

## Features

- Two entry points, **same workflow and UI**:
  - **App drawer** on the patient chart (`patient_specific` scope).
  - **Provider Companion**, as a tab on the patient's page (`provider_companion_patient_specific` scope).
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

1. The current `patient_id` comes from the Application's chart context. In the **chart app
   drawer**, `PatientDocumentCaptureApp` renders `upload_modal.html` inline and launches it as a
   modal (`content=`). In the **Provider Companion** (which renders a URL iframe, not inline
   HTML), `PatientDocumentCaptureCompanionApp` launches `GET /documents/ui?patient_id=…`, which
   serves the same template — so both surfaces drive identical UI.
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

- `applications/document_app.py` — `PatientDocumentCaptureApp` (patient-chart app-drawer entry,
  inline modal) and `PatientDocumentCaptureCompanionApp` (Provider Companion patient-tab entry,
  served-URL modal). The companion subclasses the former; both share one template and backend.
- `api/document_api.py` — `DocumentAPI` SimpleAPI endpoint (`GET /documents/ui` serves the modal
  for the companion; `POST /documents/submit` saves the document).
- `services/document_fhir.py` — builds the payload and creates the `DocumentReference`.
- `utils/constants.py` — document type → LOINC/category mapping, limits, secret keys.
- `templates/upload_modal.html` — self-contained capture/upload modal UI.

## Secrets

Declared in `CANVAS_MANIFEST.json` as **sensitive variables** (write-only — masked in
the Admin UI and shown as `[set] (sensitive)` in `canvas config list`):

| Variable | Purpose |
|----------|---------|
| `CANVAS_FHIR_CLIENT_ID` | OAuth client id for the Canvas FHIR API (write `DocumentReference`). |
| `CANVAS_FHIR_CLIENT_SECRET` | Corresponding OAuth client secret. |

Create a Canvas API application with permission to write `DocumentReference` resources
and set these values on the plugin's configuration page after install. Read at runtime via
`self.secrets[...]`.

## Limits

- Up to 20 pages per document.
- Combined PDF capped at 10 MB (checked client-side before upload and enforced
  server-side via `MAX_PDF_BYTES`).
- Title capped at 255 characters; sanitized to a single line.
- Document date must be a real date no later than today.
