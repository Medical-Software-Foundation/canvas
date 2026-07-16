# External Documents Viewer

## What it does

Adds a patient-scoped **External Documents** application to the right chart
pane. For the open patient it fetches a per-patient document index from Amazon
S3 and renders a searchable, sortable list of historical documents grouped by
category. Clicking a row opens that document through a short-lived presigned S3
URL, so the underlying bucket never has to be public.

It's built for surfacing historical records that live outside Canvas — for
example, documents migrated from a legacy EMR — without importing them into the
chart.

## Reference plugin

This is a reference implementation. It ships with **no customer or patient
data**; every example value is synthetic. Adapt the S3 layout, secrets, and
data-prep scripts to your own environment before deploying.

## How it works

1. **`ExternalDocumentsViewerApp`** (`applications/external_documents_app.py`) —
   an `Application` handler. On open it resolves the patient, downloads that
   patient's index JSON from S3, generates presigned URLs for each document, and
   renders `templates/document_viewer.html` into a `LaunchModalEffect` targeting
   the right chart pane.
2. **`ExternalDocumentsAPI`** (`applications/external_documents_api.py`) — a
   staff-session-authenticated `SimpleAPI` exposing `GET /document-url/<s3_key>`,
   which returns a fresh presigned URL for a given document key. Used to refresh
   links that may have expired while the pane is open.

### Expected S3 layout

```
s3://<S3_BUCKET>/<S3_PREFIX>/patient-indices/<canvas_patient_uuid>.json
s3://<S3_BUCKET>/<S3_PREFIX>/<document s3_key from the index>
```

Each per-patient index JSON has the shape:

```json
{
  "documents": [
    {
      "title": "Sample Lab Result",
      "category": "Lab",
      "date": "2025-02-10",
      "s3_key": "PATIENT_DIR_12345/sample_lab_result.pdf"
    }
  ]
}
```

## How to install

```bash
canvas install external-documents-viewer
```

After install, configure the secrets below at
`<instance>/admin/plugin_io/plugin/<plugin_id>/change/`.

## Configuration (secrets)

| Secret | Description |
|--------|-------------|
| `S3_KEY` | AWS Access Key ID |
| `S3_SECRET` | AWS Secret Access Key |
| `S3_REGION` | AWS region (e.g., `us-west-2`) |
| `S3_BUCKET` | S3 bucket name |
| `S3_PREFIX` | Optional key prefix within the bucket (e.g., `legacy_emr_documents`). Leave blank to read from the bucket root. |

Use an IAM principal scoped to read-only access on the document bucket/prefix.

## Preparing document data

Two reference scripts under `resources/scripts/` help you build and upload the
per-patient index files. Adapt them to your own document export.

1. **Generate indexes** from a flat CSV (one row per document):

   ```bash
   uv run python resources/scripts/generate_patient_indices.py \
       --csv document_index.csv \
       --out-dir patient-indices
   ```

2. **Upload** the generated indexes (and your document files) to S3:

   ```bash
   uv run python resources/scripts/upload_indices_to_s3.py \
       --bucket <your-bucket> \
       --prefix <your-prefix> \
       --region us-west-2 \
       --indices-dir patient-indices
   ```

## Security & privacy

- Documents are served via **presigned URLs** (1-hour expiry); the S3 bucket
  stays private.
- The API handler requires an authenticated staff session.
- Generated indexes and any source CSVs are git-ignored — they may contain PHI
  and **must never be committed**. Nothing in this repository contains real
  patient data.

## Testing

```bash
uv run pytest
```

## License

MIT — see [LICENSE](../LICENSE).
