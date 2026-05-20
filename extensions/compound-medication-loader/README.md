# compound-medication-loader

Bulk-load Compound Medications into a Canvas instance via a CSV upload page or an authenticated POST endpoint.

## What it does

Adds two ways to add Compound Medications to your Canvas instance's formulary:

- **App-drawer page** — staff drag-drop a CSV, review the parsed rows (with errors and duplicates flagged before submission), and click Load.
- **Authenticated POST endpoint** — programmatic loading from a script via a per-instance bearer token, for one-off migrations or syncing from an external source.

Both paths share the same row validation, dedup logic, and emit the same `CREATE_COMPOUND_MEDICATION` effects.

## Problem it solves

Adding compound medications to Canvas's formulary one at a time through the Prescribe command is tedious — a practice with a meaningful compound formulary (hormone creams, magic mouthwashes, lidocaine/prilocaine creams, custom topical preparations) can have dozens or hundreds of entries. This plugin lets staff load them all at once from a CSV and re-run the load safely without creating duplicates.

## Who it's for

Clinical and admin staff at practices that maintain a compound-medication formulary — e.g., functional-medicine clinics, pain-management practices, ketamine/psychedelic-medicine clinics, dermatology practices, or anywhere a provider needs to prescribe practice-specific custom compounds at scale.

## How to install

```
canvas install compound-medication-loader
```

For the programmatic POST endpoint, generate a bearer token per instance and set it as the `BULK_LOAD_API_KEY` plugin secret:

```
openssl rand -hex 32
```

Until that secret is set, the bearer endpoint stays disabled (`authenticate()` returns False) — only the in-app session path works.

## Configuration options

| Setting | Purpose | Required? |
|---|---|---|
| Plugin secret `BULK_LOAD_API_KEY` | Bearer token for the programmatic POST endpoint | Only if you want to load programmatically; the in-app upload page works without it |

## App-drawer flow

1. Click **Compound Medication Loader** in the Canvas app drawer.
2. Drop or browse for a CSV. Required columns: `formulation`, `potency_unit_code`, `controlled_substance`. Optional: `controlled_substance_ndc`, `active`. Codes can be either the SDK code (e.g. `C48155`) or the human label (e.g. `Gram`) — both are accepted.
3. Review the parsed rows. Errors are highlighted in red; rows whose formulation is already in Canvas are flagged in yellow ("Already in Canvas (active)" or "(inactive)") so you can see duplicates *before* you click Load. Click "Show reference codes" if you need to look up a potency or controlled-substance value.
4. Optionally toggle "Skip rows whose formulation already exists" (default on). When on, duplicates are excluded from the Load count; when off, duplicates are still attempted (useful if you want to surface server-side errors).
5. Click **Load N compounds**. Per-row results appear below.

Any logged-in Canvas staff member can use the page.

### Sample CSV

```csv
formulation,potency_unit_code,controlled_substance,controlled_substance_ndc,active
Lidocaine 2% / Prilocaine 2.5% topical cream,Gram,N,,true
Magic Mouthwash (lidocaine/diphenhydramine/maalox),Milliliter,N,,true
Compounded testosterone cream 200mg/g,Gram,Schedule III,12345678901,true
```

## API endpoints

All routes are mounted under `/plugin-io/api/compound_medication_loader`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/enums` | Valid `potency_unit_code` and `controlled_substance` codes |
| GET | `/existing` | Map of `{formulation: active}` for every compound already in the instance (used by the review UI to flag duplicates up front) |
| GET | `/ping` | Liveness probe (returns `{ok: true}` if authenticated) |
| POST | `/compound-medications` | Bulk-create compounds |

### Authentication

All routes accept either:

- `Authorization: Bearer <BULK_LOAD_API_KEY>` (programmatic), or
- a Canvas staff session cookie (in-app browser).

### POST /compound-medications

```json
{
  "skip_existing": true,
  "compounds": [
    {
      "formulation": "Lidocaine 2% / Prilocaine 2.5% topical cream",
      "potency_unit_code": "C48155",
      "controlled_substance": "N",
      "controlled_substance_ndc": null,
      "active": true
    }
  ]
}
```

- `skip_existing` (optional, default `true`) — skip rows whose `formulation` already exists, so re-runs are safe.
- `controlled_substance_ndc` is required when `controlled_substance != "N"`.
- Each row is validated independently; partial failures are reported per row.

Response:

```json
{
  "summary": {"total": 3, "created": 2, "skipped": 1, "errors": 0},
  "results": [
    {"index": 0, "formulation": "...", "already_exists": false, "existing_active": null, "status": "created"},
    {"index": 1, "formulation": "...", "already_exists": true,  "existing_active": true,  "status": "skipped", "reason": "formulation already exists (active)"},
    {"index": 2, "formulation": "...", "already_exists": false, "existing_active": null, "status": "created"}
  ]
}
```

Every result row carries `already_exists` and `existing_active` regardless of the `skip_existing` setting, so callers can show dedup status in their own UI even when they choose to attempt the create.

## Running tests

```
uv run pytest tests/
```

## Screenshots or screen recordings

<!-- TODO: Add at least one screenshot or short screen-recording link demonstrating the plugin in use. -->
