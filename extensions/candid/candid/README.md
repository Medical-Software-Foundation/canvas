# Candid Health Integration

Canvas plugin that replaces the built-in `candid_integration/` module. Handles the full claim lifecycle with Candid Health: submission, adjudication sync, patient payment reporting and syncing, and claim status banners.

## ID Glossary

Three IDs flow through this plugin and can be confused if you're not careful:

| ID | Source | Format | Where it lives |
|----|--------|--------|----------------|
| **Canvas claim ID** | Canvas | UUID (`00000000-...`) | `claim.id`, used for `ClaimEffect`, metadata lookups, and as `external_id` sent to Candid (`canvas:{claim_id}`) |
| **Candid encounter ID** | Candid returns it from `POST /encounters/v4` | UUID | Stored in claim metadata as `candid_encounters[].candid_encounter_id`. Used to `GET /encounters/v4/{id}` |
| **Candid claim ID** | Nested inside the encounter response at `claims[].claim_id` | Candid-generated | **Not stored.** Discovered at sync time, used ephemerally to query `GET /patient-payments/v4?claim_id={id}` |

In code, variables are prefixed to avoid ambiguity:
- `canvas_claim_id` — Canvas's internal UUID
- `candid_encounter_id` — Candid's encounter-level ID
- `candid_claim_id` — Candid's claim-level ID (nested inside an encounter)

The Candid encounter response has this hierarchy:

```
Encounter (encounter_id)            <- we create via POST, fetch via GET
  +-- claims[]
        +-- claim_id               <- Candid creates internally
        +-- status                 <- e.g. "era_received", "finalized_paid"
        +-- eras[]                 <- ERA IDs for dedup
        |     +-- era_id
        |     +-- check_number
        |     +-- check_date
        +-- service_lines[]        <- payment/adjustment amounts per line
              +-- procedure_code
              +-- charge_amount_cents
              +-- primary_paid_amount_cents
              +-- allowed_amount_cents
              +-- deductible_cents, coinsurance_cents, copay_cents
              +-- service_line_era_data.service_line_adjustments[]
              +-- service_line_manual_adjustments[]
```

## Features

### Claim Submission

When a claim is moved to the **QueuedForSubmission** queue, the plugin schedules a submission to Candid's `/api/encounters/v4` endpoint via the plugin's own `/submit` SimpleAPI route after a **60-second grace period** (`GRACE_PERIOD_SECONDS`). When the submit handler fires, it re-checks the claim's queue and skips the submission if the user has moved the claim out of `QueuedForSubmission` during the grace window.

- Builds the Candid encounter payload from Canvas claim data (patient, providers, diagnoses, service lines, subscribers)
- **Splits claims with >12 diagnosis codes** into a primary encounter (real service lines) and supplemental encounters (99499 CPT code at $0.01) per CMS-1500 limits
- Diagnoses are split in rank order (first 12, next 12, etc.) without reordering -- the Canvas UI's Claim Review Records (CRR) workflow lets users review and assign diagnoses across splits before submission
- Payload errors are caught per-section (patient, billing provider, etc.) and surfaced as claim comments rather than crashing the handler
- Stores Candid encounter IDs in claim metadata for traceability
- **Resubmission handling:** If the POST fails with `EncounterExternalIdUniquenessError` (the encounter already exists in Candid), the plugin looks up the existing encounter by `external_id` and PATCHes it instead. The PATCH payload excludes `diagnoses` and `service_lines` (Candid's update schema uses `diagnosis_ids` instead and does not accept service lines)
- On success: adds a claim comment with the submission date and Candid encounter IDs, adds a status banner, and moves claim to **FiledAwaitingResponse**
- On failure: adds an error comment, writes a `candid_submission_error` metadata entry, and moves claim to **NeedsCodingReview**

### Adjudication Sync (Pull-Based)

Candid has no webhooks, so the plugin pulls adjudication data via `GET /api/encounters/v4/{encounter_id}` and patient payments via `GET /api/patient-payments/v4?claim_id={candid_claim_id}`.

**Triggers:**
- **Event-driven:** When a claim enters the **Patient Balance** queue, the plugin asynchronously POSTs to its own `/sync-patient-payments` SimpleAPI route to pull just the patient payments for that claim (full ERA/adjudication sync is left to the nightly cron)
- **Manual:** The "Sync Now" button on the claim timeline application POSTs to `/claim-detail`, which runs a full adjudication sync inline
- **Nightly cron (2 AM):** Queries Canvas for all claims in **FiledAwaitingResponse**, **AdjudicatedOpenBalance**, and **PatientBalance** queues that have Candid encounter metadata, then runs full adjudication sync on each

A separate one-time **midnight cron** migrates legacy `SyncLog` rows into `candid_sync_history` metadata — see [Sync history backfill](#sync-history-backfill).

**Insurance adjudication (ERA data):**
- Fetches each encounter stored in claim metadata via `GET /encounters/v4/{candid_encounter_id}`
- Iterates `claims[].eras[]` to find new ERA IDs not yet synced
- **Delta-based posting:** Service line amounts (`primary_paid_amount_cents`, etc.) are cumulative across all ERAs. The plugin stores previously synced amounts in `candid_synced_amounts` metadata and only posts the delta for each payer tier. This correctly handles primary and secondary ERAs arriving at different times without double-posting.
- Posts payments via `ClaimEffect.post_payment()` for each payer tier where new amounts are detected:
  - **Primary insurance** -- charged, allowed, payment, contractual CO-45 write-off (charged minus allowed), ERA + manual adjustments
  - **Secondary/Tertiary insurance** -- separate `post_payment` per payer, only when that tier's amounts increase
- **Contractual adjustment:** The difference between `charge_amount_cents` and `allowed_amount_cents` is posted as a CO-45 write-off on the insurance posting
- **Patient responsibility:** Deductible (PR-1), coinsurance (PR-2), and copay (PR-3) amounts from the service lines are posted as transfer adjustments on the insurance posting (not as separate patient postings)
- **Balance transfers:** Based on the encounter's `next_responsible_party`, remaining balance is transferred to the appropriate party:
  - `"patient"` → transfers to patient
  - `"secondary"` → transfers to secondary coverage
  - `"tertiary"` → transfers to tertiary coverage
  - `"none"` / `"primary"` → no transfer
- **ERA-to-payer mapping:** ERAs are ordered by payer tier (index 0 = primary, 1 = secondary, 2 = tertiary). Each posting uses the correct ERA's check number, check date, and era_id for its description
- After payments post, the claim is moved to **PatientBalance** (if only patient balance remains) or **AdjudicatedOpenBalance** based on the encounter's per-service-line `insurance_balance_cents` and `patient_balance_cents` totals
- Each sync attempt appends an entry to the claim's `candid_sync_history` metadata (a capped, newest-first JSON list) so the timeline UI can show sync history

**Patient payment sync (Candid -> Canvas):**
- For each Candid claim within the encounter, queries `GET /patient-payments/v4?claim_id={candid_claim_id}`
- Skips payments already reported to Candid or synced on a previous run
- New payments are posted via `ClaimEffect.post_payment(claim_coverage_id="patient")`

**After sync:** updates the claim status banner with current Candid status and last sync date.

### Patient Payment Reporting (Canvas -> Candid)

When a patient payment is processed in Canvas (via the `PATIENT_PAYMENT_PROCESSED` event), the handler dispatches the raw event context to the plugin's `/report-payment` SimpleAPI route via an async `HttpRequestEffect` (same pattern as claim submission and patient payment sync). The endpoint then:

- Builds allocations mapping Canvas claim IDs to Candid encounter external IDs using `canvas:{claim_id}` (matching the `external_id` set at submission time)
- Handles partial allocations (allocated amounts go to specific encounters, remainder goes as unattributed)
- Submits the payment to Candid's `POST /api/patient-payments/v4`
- Stores the returned `patient_payment_id` on each allocated claim's metadata so the sync knows not to re-post it
- Appends a `payment_reported` entry to each allocated claim's `candid_sync_history` metadata for the timeline UI
- Skips reporting if the originating payment description matches `Candid patient payment ` — this prevents a feedback loop where a payment pulled from Candid is reported right back
- On failure, creates a Canvas Task labeled "Candid Integration" with the error details to notify clinicians

### Claim Banners

Claims processed through Candid display a status banner:
- **After submission:** "Candid: Submitted 2026-04-24 (2 encounters) | Awaiting response"
- **After sync:** "Candid: Era Received | Submitted 2026-04-24 | Last synced 2026-04-28"
- Denied/rejected claims show a **warning** banner instead of info

### Claim Timeline Application

A sidebar application that appears on `/revenue/claims/<id>` pages showing:
- Current Candid status banner (with submission-failure warning state when applicable)
- Activity timeline: submission, ERA syncs (with paid amounts), patient payments (inbound and outbound), claim comments, sync history
- Summary pills for ERA + payment counts
- **Sync Now** button to trigger a full adjudication sync on demand

The UI (HTML, CSS, and JS) lives in `static/claim-timeline.*` and is served by the `CandidAppAssets` SimpleAPI at `/plugin-io/api/candid/app/claim-timeline`. The application opens a `LaunchModalEffect(url=...)` in the `RIGHT_CHART_PANE` pointing at that page — passing the claim id as a `?claim_id=` query param, which the page exposes to its JS via a `data-claim-id` attribute — and listens for context changes so it re-points at the new claim when the user navigates (the page renders a placeholder when no claim is in context). The page's JS then calls the `/claim-detail` SimpleAPI endpoint (staff-session authenticated) to fetch timeline data and trigger the **Sync Now** full sync.

**Real-time updates:** The application opens a WebSocket to `/plugin-io/ws/candid/claim-<claim_id>/` (`CandidTimelineWebSocket`). Whenever the plugin posts effects to a claim (submit, sync, patient-payment-reported) it emits a `Broadcast({"refresh": true})` to that channel via `notify_claim_updated`, and the client re-fetches `/claim-detail`. If the WebSocket fails or closes, the client falls back to polling every 10s while the panel is visible, and attempts to reconnect every 5s.

### Candid Dashboard Application

A full-page application launched from the Canvas provider menu that lists all claims submitted to Candid with their current status. Its UI lives in `static/dashboard.*`, served by `CandidAppAssets` at `/plugin-io/api/candid/app/dashboard`; the application iframes that page via `LaunchModalEffect(url=...)`. The page's JS fetches claim data from the `/dashboard` SimpleAPI endpoint (staff-session authenticated).

- Shows patient name, Candid status, submission date, last sync date, current queue
- Highlights errors (submission failures) and denied claims
- Supports `?errors_only=true` filter to show only problematic claims
- Paginated with configurable limit (default 100, max 500)

## Architecture

```
candid/
  applications/
    claim_timeline.py         # Application: Candid activity timeline on claim pages
    candid_dashboard.py       # Application: full-page Candid claims dashboard (provider menu)
  handlers/
    on_queue_moved.py         # CLAIM_QUEUE_MOVED -> async POST to /submit or /sync-patient-payments
    on_patient_payment.py     # PATIENT_PAYMENT_PROCESSED -> async POST to /report-payment
  api/
    app.py                    # SimpleAPI: serves the apps' static HTML/CSS/JS (/app/*)
    broadcast.py              # notify_claim_updated: Broadcast effect to the claim WebSocket channel
    client.py                 # CandidClient: OAuth, submit_claim, submit_payment,
                              #   get_encounter, get_patient_payments (uses canvas_sdk Http client)
    claim_detail.py           # SimpleAPI: timeline data (GET) + manual full sync (POST) (/claim-detail)
    dashboard.py              # SimpleAPI: aggregated claim list for dashboard (/dashboard)
    payload_builder.py        # Build Candid encounter payloads with claim splitting
    report_payment.py         # SimpleAPI: report patient payment to Candid (/report-payment)
    submit.py                 # SimpleAPI: async claim submission (/submit)
    sync.py                   # SimpleAPI: trigger full adjudication sync (/sync)
                              #   and patient-payment-only sync (/sync-patient-payments)
    websocket.py              # CandidTimelineWebSocket: per-claim refresh channel
  static/                     # UI assets served by api/app.py (one file per concern)
    dashboard.html / .css / .js        # full-page Candid claims dashboard
    claim-timeline.html / .css / .js   # claim-page Candid activity timeline
  cron/
    nightly_sync.py           # 2 AM daily: sync all claims in 3 queues
  adjudication_sync.py        # Core sync logic: pull ERA + patient payments, post to Canvas
  effect_helpers.py           # Shared: banners, metadata keys, success/failure handlers
```

## Variables

Declared in `CANVAS_MANIFEST.json` under `"variables"`. Sensitive values are encrypted at rest.

| Variable | Sensitive | Description |
|----------|-----------|-------------|
| `CANDID_CLIENT_ID` | Yes | Candid OAuth2 client ID |
| `CANDID_CLIENT_SECRET` | Yes | Candid OAuth2 client secret — also used as the shared API key on the plugin's own `/submit`, `/sync`, `/sync-patient-payments`, and `/report-payment` SimpleAPI routes |
| `CANDID_BASE_URL` | No | Candid API base URL (e.g. `https://api.joincandidhealth.com`) |

The instance URL for self-calls (e.g. `/submit`, `/sync-patient-payments`) is derived automatically from `self.environment["CUSTOMER_IDENTIFIER"]` — no variable needed. The internal machine-to-machine routes (`/submit`, `/sync`, `/sync-patient-payments`, `/report-payment`) use `CANDID_CLIENT_SECRET` as a shared API key (`APIKeyCredentials`). The user-facing routes — `/claim-detail`, `/dashboard`, and the `/app/*` asset routes — require a logged-in **staff** session (`StaffSessionAuthMixin`), as does the `CandidTimelineWebSocket`.

## Claim Metadata Keys

| Key | Value | Set by |
|-----|-------|--------|
| `candid_encounters` | JSON list of `{split, candid_encounter_id, external_id}` | Submission |
| `candid_submitted_at` | ISO timestamp | Submission |
| `candid_submission_error` | JSON `{error, date}` (cleared on a successful submission) | Submission |
| `candid_last_sync_at` | ISO timestamp | Adjudication sync (and patient-payment-only sync, when it posts effects) |
| `candid_claim_status` | Candid claim status string (e.g. `era_received`, `finalized_paid`) | Adjudication sync |
| `candid_synced_adjudication_ids` | JSON list of ERA IDs already posted | Adjudication sync |
| `candid_synced_amounts` | JSON `{primary, secondary, tertiary}` cumulative paid cents posted so far | Adjudication sync |
| `candid_synced_payment_ids` | JSON list of patient payment IDs synced from Candid | Adjudication sync / patient-payment sync |
| `candid_reported_payment_ids` | JSON list of patient payment IDs we reported to Candid | Patient payment handler |
| `candid_sync_history` | JSON list (newest-first, capped at 20) of activity entries `{synced_at, log_type, status, effects, era_ids, detail}` for the timeline UI | Adjudication sync / patient payment handler |

## Idempotency

### Insurance adjudications

The sync uses two dedup mechanisms:
- **ERA ID dedup:** Before processing, the plugin checks if all `era_id`s appear in `candid_synced_adjudication_ids` metadata. If all are already synced, the claim is skipped. New ERA IDs are written to metadata in the same effect batch.
- **Amount-based delta:** Service line amounts are cumulative across all ERAs. The plugin stores previously synced totals in `candid_synced_amounts` (`{primary, secondary, tertiary}` in cents) and only posts a payer tier when its total has increased since the last sync. This handles primary and secondary ERAs arriving weeks apart — the primary payment is posted on the first sync, and only the secondary delta is posted on the second sync without re-posting primary.

### Patient payments

Patient payments are deduped by `patient_payment_id` across two sources:
- **Outbound** (Canvas -> Candid): When we report a payment, Candid returns a `patient_payment_id` which we store in `candid_reported_payment_ids`
- **Inbound** (Candid -> Canvas): When the sync pulls patient payments, it checks against both reported and previously-synced IDs before posting. Synced IDs are written to `candid_synced_payment_ids` in the same effect batch

This prevents double-posting regardless of whether the payment originated in Canvas or in Candid.

## Sync history

Sync history lives on each claim's `candid_sync_history` metadata — a JSON list (newest-first, capped at 20) of activity entries appended by the adjudication sync and the patient-payment handler (see [Claim Metadata Keys](#claim-metadata-keys)). The cap is applied on write, so the list is bounded by construction.

> **History:** activity originally lived in a `SyncLog` custom data model (one row per event per claim), which required a nightly pruning job to bound its growth. It was migrated into `candid_sync_history` metadata by a one-time midnight cron (`CandidSyncHistoryBackfill`) that merged legacy rows under any existing entries, then deleted them. Once that backfill had run in every environment, the cron, the `SyncLog` model, and its table were removed.

## Rollout

The home-app `candid_integration/signals.py` module checks whether this plugin is active before dispatching built-in Celery tasks. This acts as a kill-switch: disabling the plugin in the Canvas admin immediately re-enables the built-in integration with no code deploy needed.

## Testing

```sh
cd candid
uv run pytest tests/ -v
```

