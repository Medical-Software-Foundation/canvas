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
- Add a coverage: payer, member ID, rank, plan type, subscriber relationship, dates, optional front/back card photos.
- Edit any existing coverage with a partial update (only fields you change are sent).
- Expire a coverage with an end date (audit-logged).
- Remove a coverage (soft-remove via stack flip; audit-logged).
- Reorder the entire stack in one effect.

## Card photos

Card photos use the platform's `upload_files=True` SimpleAPI primitive. The browser POSTs `multipart/form-data` to `/cards/upload`; the platform uploads each file part to S3 under `plugin-uploads/patient_coverage_companion/...` and hands the resulting keys back to the plugin. The next coverage save call carries those keys on `card_image_front_upload_key` / `card_image_back_upload_key`, and the platform-side interpreter performs a **server-side S3 copy** into the coverage's image storage — no bytes ever pass through the plugin.

On mobile, the `<input type="file" accept="image/*" capture="environment">` field opens the rear camera natively. On desktop it falls back to a file picker.

## Dependencies

- Canvas SDK ≥ 0.1.4
- `canvas_sdk.effects.coverage` (Coverage create / update / expire / remove / remove_photo + CoverageReorder)
- `canvas_sdk.effects.patient_identification_card` (PatientIdentificationCard create / update / delete)
- Both shipped under [KOALA-5549](https://canvasmedical.atlassian.net/browse/KOALA-5549).

## Endpoints

All under `/plugin-io/api/patient_coverage_companion/app/`:

| Method | Path                                        | Purpose                          |
|--------|---------------------------------------------|----------------------------------|
| GET    | `/`                                         | HTML shell                       |
| GET    | `/main.js`, `/styles.css`                   | Static assets                    |
| GET    | `/data.json?patient_id=X`                   | Coverages + dropdown options     |
| GET    | `/payers/search?q=Y`                        | Payer (Transactor) type-ahead    |
| POST   | `/cards/upload` (`upload_files=True`)       | File upload → S3 keys (any field name) |
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
