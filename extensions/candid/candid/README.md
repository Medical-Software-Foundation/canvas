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
              +-- service_line_manual_adjustments[]
```

## Features

### Claim Submission

When a claim is moved to the **QueuedForSubmission** queue, the plugin schedules a submission to Candid's `/api/encounters/v4` endpoint after a **60-second grace period** (allowing users to undo accidental queue moves).

- Builds the Candid encounter payload from Canvas claim data (patient, providers, diagnoses, service lines, subscribers)
- **Splits claims with >12 diagnosis codes** into a primary encounter (real service lines) and supplemental encounters (99499 CPT code at $0.01) per CMS-1500 limits
- Diagnoses are split in rank order (first 12, next 12, etc.) without reordering -- the Canvas UI's Claim Review Records (CRR) workflow lets users review and assign diagnoses across splits before submission
- Payload errors are caught per-section (patient, billing provider, etc.) and surfaced as claim comments rather than crashing the handler
- Stores Candid encounter IDs in claim metadata for traceability
- On success: adds a claim comment with the submission date and Candid encounter IDs, adds a status banner, and moves claim to **FiledAwaitingResponse**
- On failure: adds an error comment and moves claim to **NeedsCodingReview**

### Adjudication Sync (Pull-Based)

Candid has no webhooks, so the plugin pulls adjudication data via `GET /api/encounters/v4/{encounter_id}` and patient payments via `GET /api/patient-payments/v4?claim_id={candid_claim_id}`.

**Triggers:**
- **Event-driven:** When a claim enters the **Patient Balance** queue, the plugin syncs patient payments immediately
- **Nightly cron (2 AM):** Queries Canvas for all claims in **FiledAwaitingResponse**, **AdjudicatedOpenBalance**, and **PatientBalance** queues that have Candid encounter metadata, then runs full adjudication sync on each

**Insurance adjudication (ERA data):**
- Fetches each encounter stored in claim metadata via `GET /encounters/v4/{candid_encounter_id}`
- Iterates `claims[].eras[]` to find new ERA IDs not yet synced
- For each new ERA, maps Candid service line amounts to Canvas `LineItemTransaction` objects
- Posts payments via `ClaimEffect.post_payment()` for each payer tier:
  - **Primary insurance** -- charged, allowed, payment, ERA + manual adjustments (CO-45, etc.)
  - **Secondary/Tertiary insurance** -- separate `post_payment` per payer
  - **Patient responsibility** -- deductible (PR-1), coinsurance (PR-2), copay (PR-3), posted under the patient coverage
- When the encounter's `next_responsible_party` is `patient`, primary insurance adjustments include `transfer_remaining_balance_to="patient"` so any remaining balance moves to the patient
- After payments post, the claim is moved to **PatientBalance** (if only patient balance remains) or **AdjudicatedOpenBalance** based on the encounter's per-service-line balances

**Patient payment sync (Candid -> Canvas):**
- For each Candid claim within the encounter, queries `GET /patient-payments/v4?claim_id={candid_claim_id}`
- Skips payments already reported to Candid or synced on a previous run
- New payments are posted via `ClaimEffect.post_payment(claim_coverage_id="patient")`

**After sync:** updates the claim status banner with current Candid status and last sync date.

### Patient Payment Reporting (Canvas -> Candid)

When a patient payment is processed in Canvas (via the `PATIENT_PAYMENT_PROCESSED` event), the plugin reports it to Candid's `POST /api/patient-payments/v4` endpoint.

- Maps Canvas claim allocations to Candid encounter external IDs using stored metadata
- Handles partial allocations (allocated amounts go to specific encounters, remainder goes as unattributed)
- Supports payments across multiple claims
- Stores the returned `patient_payment_id` on each allocated claim's metadata so the sync knows not to re-post it

### Claim Banners

Claims processed through Candid display a status banner:
- **After submission:** "Candid: Submitted 2026-04-24 (2 encounters) | Awaiting response"
- **After sync:** "Candid: Era Received | Submitted 2026-04-24 | Last synced 2026-04-28"
- Denied/rejected claims show a **warning** banner instead of info

### Claim Timeline Application

A sidebar application that appears on `/revenue/claims/<id>` pages showing:
- Current Candid status banner
- Submission details with encounter IDs
- Synced ERA IDs and patient payment IDs
- Summary counts
- **Sync Now** button to trigger a full adjudication sync on demand

The application uses the `/claim-detail` SimpleAPI endpoint (authenticated via Canvas user session, not API key) to fetch timeline data and trigger syncs.

## Architecture

```
candid/
  applications/
    claim_timeline.py         # Application: Candid activity timeline on claim pages
  handlers/
    on_queue_moved.py         # CLAIM_QUEUE_MOVED -> submit (delayed) or sync
    on_patient_payment.py     # PATIENT_PAYMENT_PROCESSED -> report to Candid
  api/
    client.py                 # CandidClient: OAuth, submit_claim, submit_payment,
                              #   get_encounter, get_patient_payments
    claim_detail.py           # SimpleAPI: timeline data + manual sync (/claim-detail)
    payload_builder.py        # Build Candid encounter payloads with claim splitting
    submit.py                 # SimpleAPI: delayed claim submission (/submit)
    sync.py                   # SimpleAPI: trigger full adjudication sync (/sync)
  cron/
    nightly_sync.py           # 2 AM daily: sync all claims in 3 queues
  models/
    sync_state.py             # SyncLog custom model: per-claim sync history for the timeline UI
  adjudication_sync.py        # Core sync logic: pull ERA + patient payments, post to Canvas
  effect_helpers.py           # Shared: banners, metadata keys, success/failure handlers
```

## Secrets

| Secret | Description |
|--------|-------------|
| `CANDID_CLIENT_ID` | Candid OAuth2 client ID |
| `CANDID_CLIENT_SECRET` | Candid OAuth2 client secret |
| `CANDID_BASE_URL` | Candid API base URL (e.g. `https://api.joincandidhealth.com`) |
| `CANVAS_INSTANCE_URL` | Public URL of this Canvas instance (for delayed self-call to `/submit`) |
| `CANDID_API_KEY` | Shared secret for authenticating the SimpleAPI endpoints |

## Claim Metadata Keys

| Key | Value | Set by |
|-----|-------|--------|
| `candid_encounters` | JSON list of `{split, candid_encounter_id, external_id}` | Submission |
| `candid_submitted_at` | ISO timestamp | Submission |
| `candid_last_sync_at` | ISO timestamp | Adjudication sync |
| `candid_claim_status` | Candid claim status string (e.g. `era_received`, `finalized_paid`) | Adjudication sync |
| `candid_synced_adjudication_ids` | JSON list of ERA IDs already posted | Adjudication sync |
| `candid_synced_payment_ids` | JSON list of patient payment IDs synced from Candid | Adjudication sync |
| `candid_reported_payment_ids` | JSON list of patient payment IDs we reported to Candid | Patient payment handler |

## Idempotency

### Insurance adjudications

The sync deduplicates by Candid's `era_id` (a unique identifier per remittance advice event):
- Before posting payments for an ERA, the plugin checks if the `era_id` appears in `candid_synced_adjudication_ids` metadata
- After posting, the `era_id` is written to metadata in the same effect batch
- Multiple ERAs on the same claim (e.g., primary then secondary adjudication) each get their own `era_id` and are processed independently

### Patient payments

Patient payments are deduped by `patient_payment_id` across two sources:
- **Outbound** (Canvas -> Candid): When we report a payment, Candid returns a `patient_payment_id` which we store in `candid_reported_payment_ids`
- **Inbound** (Candid -> Canvas): When the sync pulls patient payments, it checks against both reported and previously-synced IDs before posting. Synced IDs are written to `candid_synced_payment_ids` in the same effect batch

This prevents double-posting regardless of whether the payment originated in Canvas or in Candid.

## Rollout

The home-app `candid_integration/signals.py` module checks whether this plugin is active before dispatching built-in Celery tasks. This acts as a kill-switch: disabling the plugin in the Canvas admin immediately re-enables the built-in integration with no code deploy needed.

## Testing

```sh
cd ~/candid
uv run pytest tests/ -v
```
