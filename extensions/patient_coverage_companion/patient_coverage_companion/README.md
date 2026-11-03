# Patient Coverage Companion

Patient-scope provider companion app for managing the patient's cards on file:

1. **Insurance coverages** — list, add, edit, expire, remove, reorder, with front/back insurance-card photo capture.
2. **ID cards** — list, add, edit, delete identification cards (driver license, passport, etc.) with a single image per card.

The launch screen is a mode selector with two tiles; pick a mode to enter its flow. The two modes are independent — no shared list view.

All photo capture uses the rear camera natively on mobile (via `<input type="file" capture="environment">`) and a file picker on desktop.

## Surface

- **Scope:** `provider_companion_patient_specific` — appears as a tab on the patient page in the companion app.
- **Tech:** vanilla JS (no bundler), SimpleAPI handler in Python, plain CSS. Same shape as `provider_patient_profile_companion`.
- **Auth:** `StaffSessionAuthMixin` on every endpoint. The platform-side effect interpreters additionally enforce `ModelPermissions` + `ParentPatientObjectPermissions` — this plugin is not the only line of defense.

## What it does

- Lists the patient's active coverages, grouped by stack and rank.
- Add a coverage: payer, member ID, rank, subscriber relationship, dates, optional front/back card photos. Plan type is not editable here: it follows the payer.
- Edit any existing coverage with a partial update (only fields you change are sent).
- Expire a coverage with an end date (audit-logged).
- Remove a coverage (soft-remove via stack flip; audit-logged).
- Reorder the entire stack in one effect.

## Card photos

Card photos use the SimpleAPI `file_uploads="stored"` route option. The browser POSTs `multipart/form-data` to `/cards/upload`; Canvas stores each file part before the plugin runs and hands the plugin a `StoredFilePart` per file, carrying either an upload key (`plugin-uploads/...`) or an error code. If any part fails, the endpoint returns 502 and no keys, so a coverage is never saved with one side silently missing. The next coverage save call carries those keys on `card_image_front_upload_key` / `card_image_back_upload_key`, and the platform-side interpreter performs a **server-side S3 copy** into the coverage's image storage — no bytes ever pass through the plugin.

On mobile, the `<input type="file" accept="image/*" capture="environment">` field opens the rear camera natively. On desktop it falls back to a file picker.

## Dependencies

- Canvas SDK ≥ 0.264.0 (Canvas release 1.372 or later)
- `canvas_sdk.effects.coverage` (Coverage create / update / expire / remove / remove_photo + CoverageReorder)
- `canvas_sdk.effects.patient` (PatientIdentificationCard create / update / delete)
- SimpleAPI `file_uploads="stored"` routes
- Shipped in canvas-plugins #1931.

The Coverage effect validates when the endpoint calls it (payer exists, rank is free among active coverages, subscriber rules, upload key prefix). The endpoints turn those errors into field-level 400s, so the form shows them inline instead of reporting a save that later fails.

Known limit: the form has no subscriber picker, so only "Self" works as the relationship. Other relationships need a subscriber patient, which the SDK requires.

## Endpoints

All under `/plugin-io/api/patient_coverage_companion/app/`:

| Method | Path                                        | Purpose                          |
|--------|---------------------------------------------|----------------------------------|
| GET    | `/`                                         | HTML shell                       |
| GET    | `/main.js`, `/styles.css`                   | Static assets                    |
| GET    | `/data.json?patient_id=X`                   | Coverages + dropdown options     |
| GET    | `/payers/search?q=Y`                        | Payer (Transactor) type-ahead    |
| POST   | `/cards/upload` (`file_uploads="stored"`) | File upload → upload keys (any field name) |
| POST   | `/coverage`                                 | Create coverage                  |
| POST   | `/coverage/<id>`                            | Update coverage (partial)        |
| POST   | `/coverage/<id>/remove`                     | Remove coverage                  |
| POST   | `/coverage/<id>/expire`                     | Expire coverage with end date    |
| POST   | `/coverage/<id>/photo/<side>/remove`        | Clear front or back card photo   |
| POST   | `/coverages/reorder`                        | Reorder ranks in one call        |
| GET    | `/id-cards.json?patient_id=X`               | ID cards for the patient         |
| POST   | `/id-card`                                  | Create ID card                   |
| POST   | `/id-card/<id>`                             | Update ID card (partial)         |
| POST   | `/id-card/<id>/delete`                      | Delete ID card                   |
