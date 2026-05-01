# Portal Membership

A Canvas plugin that manages patient membership sign-up, recurring monthly billing via Stripe, and cancellation — all driven from the patient portal.

## Features

- Patients sign up via the patient portal, pay upfront, and their card is stored for monthly billing
- Monthly charges fire on the same calendar day each month via a Canvas CronTask (no Stripe Subscriptions or webhooks required)
- Up to two automatic retries (1 day apart) on payment failure; auto-cancellation after three consecutive failures
- Patients can cancel from the portal; a "Cancelled Membership" banner appears on their chart and staff receive a task
- Patients can restart from the portal; the banner is cleared and billing resumes
- Membership tiers and pricing are fully configurable via plugin secrets
- Discount codes with percentage or fixed-cents off, for a configurable number of billing cycles
- Patient-facing charge history (Charges tab on the membership page), capped at the last 24 entries
- Staff-facing **Memberships** application (provider top menu) with a read-only directory of all memberships

## Architecture

```
portal_membership/
├── models/
│   ├── membership.py         # CustomModel — one row per patient
│   └── charge_record.py      # CustomModel — one row per billing attempt
├── applications/
│   └── membership_admin_app.py  # Application — Memberships entry in provider menu
├── protocols/
│   ├── membership_api.py     # SimpleAPI — patient portal HTTP endpoints
│   ├── admin_api.py          # SimpleAPI — staff directory page + JSON
│   ├── billing_cron.py       # CronTask — daily billing (09:00 UTC)
│   ├── membership_card.py    # BannerAlert on chart + appointment cards
│   └── portal_widget.py      # Portal landing-page widget
├── payment_processor/
│   ├── base.py               # Abstract PaymentProcessor interface
│   └── stripe_processor.py   # Stripe implementation
└── utils/
    ├── membership_store.py   # ORM wrapper over Membership (dict API)
    ├── charge_history.py     # ORM wrapper over ChargeRecord
    └── discount.py           # Discount code parsing + application
```

## Storage

Membership state and charge history are persisted in plugin-scoped custom
data tables (namespace `portal__membership`) — not the plugin cache. This
avoids the 14-day TTL cap that previously would have expired records between
monthly billing cycles. History has no bounded size beyond Canvas's normal
storage limits; `/history` defaults to returning the last 50 entries.

## API Endpoints

Base URL: `https://<instance>.canvasmedical.com/plugin-io/api/portal_membership/membership`

All endpoints require an authenticated patient portal session.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/plans` | List available membership tiers |
| GET | `/status` | Current membership status for the patient (includes active discount if any) |
| GET | `/page` | Membership management HTML page |
| POST | `/signup` | Enrol and charge upfront (accepts optional `discount_code`) |
| POST | `/cancel` | Cancel membership |
| POST | `/restart` | Re-activate membership (accepts optional `discount_code`) |
| POST | `/validate-code` | Preview the discounted amount for a `plan_key` + `code` (no state change) |
| POST | `/update-payment-method` | Replace the Stripe PaymentMethod on file (no charge) |
| GET | `/history` | Patient's charge history, newest-first (includes failed attempts; no Stripe IDs or raw errors) |

### Staff Directory

A separate set of endpoints under `/admin` backs the **Memberships** application that staff open from the provider top menu. These require an authenticated staff session.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/page` | Staff HTML directory page (Canvas dark theme) |
| GET | `/admin/memberships` | JSON list of all memberships, joined with patient name + DOB. Optional `status` query param: `all` (default), `active`, `cancelled`. |

Patient names link to the chart in a new tab. The directory is intentionally read-only — staff redirect patients to the portal to manage their own memberships.

## Secrets

Set these after deploying via `uv run canvas config set portal_membership <KEY>=<VALUE>`:

| Secret | Description | Example |
|--------|-------------|---------|
| `STRIPE_SECRET_KEY` | Stripe API secret key | `sk_live_...` |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key (injected into the patient-facing page for Stripe Elements) | `pk_live_...` |
| `MEMBERSHIP_PLANS` | JSON array of plan configs (see below) | `[{"name":"Basic","key":"basic","price_cents":4900,"cadence":"monthly"},{"name":"Gold","key":"gold","price_cents":9900,"cadence":"annually"}]` |
| `DISCOUNT_CODES` | JSON array of discount codes (see below); optional | `[{"code":"WELCOME10","type":"percent","value":10,"months":3}]` |
| `STAFF_OFFBOARDING_TEAM_ID` | Canvas team UUID for cancellation tasks | `e4f7a1b2-...` |
| `BILLING_CURRENCY` | ISO currency code | `usd` |
| `namespace_read_write_access_key` | Custom-data access key (auto-declared because the plugin has a `custom_data` block; set by Canvas admin on install) | (set by admin) |

### Plan format

Each entry in `MEMBERSHIP_PLANS` is an object with these fields:

| Field | Required | Description |
|---|---|---|
| `name` | yes | Display name shown to patients (e.g. `"Gold"`). |
| `key` | yes | Stable identifier used in the API (`/signup`, `/restart`). |
| `price_cents` | yes | Price in cents charged each cycle. |
| `description` | no | Short blurb shown under the plan in the patient signup dropdown. Empty when absent. |
| `cadence` | no | One of `"daily"`, `"weekly"`, `"monthly"`, `"quarterly"`, `"annually"`. Defaults to `"monthly"` when absent. Determines the billing-cycle length: daily = +1 day, weekly = +7 days, monthly = same day next month (clamped to month-end when needed), quarterly = same day +3 months (clamped), annually = same day next year (Feb 29 → Feb 28 on non-leap years). Cadence is a **practice configuration** — patients cannot change it. |

The cadence the patient signed up under is captured on the membership record, so changing a plan's cadence in the secret does not retroactively shift existing members.

### Discount code format

Each code in `DISCOUNT_CODES` is an object with these fields:

| Field | Required | Description |
|---|---|---|
| `code` | yes | Patient-entered string. Matched case-insensitively; whitespace trimmed. |
| `type` | yes | `"percent"` or `"fixed"`. |
| `value` | yes | Percent off (0–100) for `percent`, or cents off for `fixed`. |
| `months` | yes | Total billing cycles to apply the discount to, **including the upfront signup charge**. `months: 3` = signup + 2 cron charges at the discounted rate. The cycle length follows the plan's `cadence` — for an annual plan, `months: 3` means three years of discount. The field is named `months` for backwards compatibility. |
| `expires_at` | no | ISO-8601 date. Codes are rejected on or after this date. |

Behavior notes:
- A `discount_cycles_remaining` counter on each member's record decrements **only on successful charges**. A failed charge + retry does not burn a cycle.
- A 100% discount short-circuits the Stripe call (Stripe rejects sub-$0.50 charges) and is logged as a successful $0 cycle.
- When the counter reaches zero, the discount fields are removed from the record and full-price billing resumes.
- Changing the code definition in the secret does **not** retroactively change active memberships — the discount terms are captured on the record at signup time.

## Membership Record Fields

Stored as a row in the `Membership` custom model (one per patient):

| Field | Type | Notes |
|---|---|---|
| `patient_id` | UUID | Canvas patient identifier, indexed |
| `plan` / `plan_name` | text | Plan key and display name |
| `status` | text | `"active"` or `"cancelled"` |
| `stripe_customer_id`, `payment_method_id` | text | Stripe identifiers |
| `amount_cents`, `currency`, `cadence`, `billing_day` | int / text / text / int | Base billing config; `cadence` is captured from the plan at signup |
| `next_billing_date`, `retry_date` | date | Retry is nullable |
| `consecutive_failures` | int | 0, 1, or 2 (auto-cancel at 2) |
| `discount_code`, `discount_type`, `discount_value`, `discount_cycles_remaining` | text / text / int / int | Zero / empty when no active discount; cycles follow the plan cadence |
| `created_at`, `updated_at` | datetime | Auto-managed |

Charge attempts are stored in the `ChargeRecord` custom model keyed by
`patient_id` — one row per billing attempt (success or failure), surfaced
via `GET /history`.

## Billing Retry Policy

Three total attempts, 1 day apart:

1. **Attempt 1** — fires on the patient's `next_billing_date`. On failure, schedules a retry the next day (`retry_date`) and logs a warning. The patient stays active; `consecutive_failures` becomes 1.
2. **Attempt 2** — fires on the retry date. On failure, schedules another retry the day after; `consecutive_failures` becomes 2.
3. **Attempt 3** — fires on the second retry date. On failure, the membership is auto-cancelled, the chart status banner refreshes to show the cancelled state, and a staff off-boarding task is created.

Each failed attempt is recorded in the patient's charge history with a description noting the attempt number (e.g. `attempt 2 of 3, retry scheduled`).

## Deployment

```bash
# Deploy to a Canvas instance
uv run canvas install portal-membership --host <instance>

# Set secrets
uv run canvas config set portal_membership \
  STRIPE_SECRET_KEY=sk_test_... \
  "MEMBERSHIP_PLANS=[{\"name\":\"Basic\",\"key\":\"basic\",\"price_cents\":4900}]" \
  STAFF_OFFBOARDING_TEAM_ID=<team-uuid> \
  BILLING_CURRENCY=usd
```
