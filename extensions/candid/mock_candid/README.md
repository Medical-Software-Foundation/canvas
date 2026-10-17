# Mock Candid Health API

## What it does

A Canvas plugin that stands in for Candid Health's API. Install it next to the `candid` plugin on a test instance, point the candid plugin at it, and the candid plugin submits claims, pulls remittances (ERAs), and reports patient payments against the mock instead of Candid. You script which remittances each claim gets, so you can run the candid plugin's whole claim lifecycle on demand.

## Problem it solves

The parts of the candid plugin that post payments, adjustments, and balance transfers only run when a claim has remittances, and real ones only arrive after a payer adjudicates the claim. This mock returns the remittances you set up, claim by claim, including a primary remittance followed later by a secondary one.

It keeps everything (encounters, scenarios, payments) in the plugin cache, so every web container on the instance sees the same data and it survives restarts and deploys. Each item expires 14 days after it was last written.

## Who it's for

Engineers and QA testing changes to the candid plugin on a test instance. Use test patients only: the mock stores the claim payloads the candid plugin sends.

## How to install

1. From `extensions/candid/`, install the mock next to the candid plugin:
   ```sh
   canvas install mock_candid --host <instance>
   ```
2. Set the mock's `MOCK_CANDID_API_KEY` variable to a random value without commas (e.g. `openssl rand -hex 32`).
3. Set the candid plugin's `CANDID_BASE_URL` to `https://<instance>/plugin-io/api/mock_candid`. Leave its client ID and secret as they are: the mock accepts any credentials unless you configure `valid_client_id` / `valid_client_secret`.
4. Enable both plugins.

To go back to real Candid, set `CANDID_BASE_URL` back. The candid plugin caches its login token for 4.5 hours per client ID and doesn't retry on a 401, so Candid rejects calls until the token it got from the mock expires.

## Configuration options

| Variable | Sensitive | Description |
|----------|-----------|-------------|
| `MOCK_CANDID_API_KEY` | Yes | API key for the test-control endpoints, sent as the `Authorization` header. Control requests are refused while it's unset. |

Everything else is set through the endpoints below.

## Endpoints

### Test control (needs `Authorization: <MOCK_CANDID_API_KEY>`)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/scenario` | Set the remittance data for one claim |
| `POST` | `/configure` | Set the global config: adjudication data for claims without a scenario, failure simulation, passthrough. `{"reset": true}` clears all mock data |
| `POST` | `/inject-patient-payment` | Add a patient payment as if Candid received it outside Canvas |
| `GET` | `/status` | All encounters, scenarios, and payments. `?claim_id=<id>` shows one claim: its scenario, the encounter exactly as the candid plugin will see it, and its payments |

### Candid API (called by the candid plugin)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/auth/v2/token` | Returns a mock OAuth token |
| `POST` | `/api/encounters/v4` | Stores the encounter, returns its `encounter_id` |
| `GET` | `/api/encounters/v4/<id>` | Returns the encounter with its scenario's (or the global) adjudication data |
| `POST` | `/api/patient-payments/v4` | Stores a patient payment, returns its `patient_payment_id` |
| `GET` | `/api/patient-payments/v4?claim_id=<id>` | Patient payments for a Candid claim |

## Scenarios

A scenario holds one claim's remittance data. Target the claim with `claim_id` (the Canvas claim id; once a claim is submitted, `GET /status` lists it as `canvas:<claim id>`), or with `external_id`. You can set a scenario before or after the claim is submitted.

| Field | Meaning |
|-------|---------|
| `encounter_status` | Candid claim status, e.g. `era_received`, `finalized_paid` (default `coded`) |
| `eras` | ERAs in payer order: primary, secondary, tertiary. Each needs an `era_id`; `check_number` and `check_date` are optional |
| `allowed_amount_cents`, `primary_paid_amount_cents`, `secondary_paid_amount_cents`, `tertiary_paid_amount_cents` | Payer amounts |
| `deductible_cents`, `coinsurance_cents`, `copay_cents` | Patient responsibility from the primary |
| `insurance_balance_cents`, `patient_balance_cents` | Balances Candid reports. The candid plugin picks the claim's queue from these |
| `next_responsible_party` | `primary`, `secondary`, `tertiary`, `patient` or `none` |
| `service_line_era_adjustments`, `service_line_manual_adjustments` | Adjustment lists placed on each service line |

- Amounts apply to every service line of the encounter, so single-line claims are easiest to check.
- Each `POST /scenario` merges into the claim's existing scenario. `eras` is replaced as a whole, so send every ERA so far. Add `"reset": true` to start the claim's scenario over.
- A claim with a scenario ignores the global adjudication config. Claims without one use the global config.
- Unknown fields are listed under `ignored` in the response, to catch typos.
- A claim with more than 12 diagnoses is split into several encounters. The scenario applies to its main encounter; the extra encounters use the global config.

The candid plugin only pulls remittances on its nightly sync or when someone clicks **Sync Now** on the claim's Candid Activity panel. Moving a claim into Patient Balance only pulls patient payments.

### Example: primary remittance, then the secondary

```sh
BASE=https://<instance>/plugin-io/api/mock_candid
KEY=<MOCK_CANDID_API_KEY>

# 1. The primary pays $100 of a $200 line and assigns $50 of patient responsibility
curl -X POST "$BASE/scenario" -H "Authorization: $KEY" -H "Content-Type: application/json" -d '{
  "claim_id": "<canvas claim id>",
  "encounter_status": "era_received",
  "eras": [{"era_id": "era-primary-1", "check_number": "CHK001", "check_date": "2026-10-15"}],
  "allowed_amount_cents": 15000,
  "primary_paid_amount_cents": 10000,
  "deductible_cents": 3000,
  "coinsurance_cents": 2000,
  "insurance_balance_cents": 5000,
  "patient_balance_cents": 0,
  "next_responsible_party": "secondary"
}'

# 2. Later, the secondary pays $35 and the patient owes the rest
curl -X POST "$BASE/scenario" -H "Authorization: $KEY" -H "Content-Type: application/json" -d '{
  "claim_id": "<canvas claim id>",
  "eras": [
    {"era_id": "era-primary-1", "check_number": "CHK001", "check_date": "2026-10-15"},
    {"era_id": "era-secondary-1", "check_number": "CHK002", "check_date": "2026-10-16"}
  ],
  "secondary_paid_amount_cents": 3500,
  "insurance_balance_cents": 0,
  "patient_balance_cents": 1500,
  "next_responsible_party": "patient"
}'

# See what the candid plugin will get for the claim
curl "$BASE/status?claim_id=<canvas claim id>" -H "Authorization: $KEY"
```

Other cases are variations on the same calls:

- **Both remittances at once:** make both calls before the claim's first sync.
- **The secondary writes off the rest:** in step 2, set `next_responsible_party` to `none`.
- **A $0 secondary:** in step 2, add the secondary ERA but leave `secondary_paid_amount_cents` out.
- **Tertiary:** give the claim three coverages and, in step 2, set `next_responsible_party` to `tertiary`.

### Simulating failures (global config)

```sh
curl -X POST "$BASE/configure" -H "Authorization: $KEY" -H "Content-Type: application/json" -d '{
  "fail_next_encounter_submit": true,
  "encounter_submit_error": {
    "status_code": 422,
    "errorName": "HttpRequestValidationError",
    "content": {"fieldName": "diagnoses", "humanReadableMessage": "At least one diagnosis is required"}
  }
}'
```

The next claim submission fails with that error, and the one after succeeds. `fail_next_payment_submit` / `payment_submit_error` do the same for patient payment reporting.

### Passthrough

`POST /configure {"passthrough_base_url": "https://api-staging.joincandidhealth.com"}` forwards every `/api/*` request to that Candid environment, with the candid plugin's own credentials. Set it back to `null` to return to mock responses.
