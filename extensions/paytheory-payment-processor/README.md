# PayTheory Payment Processor

## What it does

PayTheory Payment Processor lets a Canvas practice collect credit card payments with [PayTheory](https://paytheory.com) without leaving the clinical workflow. It registers as a Canvas card payment processor, so the standard **Collect Payment** modal renders PayTheory's PCI-compliant hosted card fields, tokenizes the card in the browser, and charges it server-side through PayTheory's GraphQL API. Cards can be saved per patient, listed, and removed, and the same saved card is reused on later visits.

The plugin never sees raw card numbers — PayTheory's SDK tokenizes the card client-side and the server only ever handles the resulting payment-method token.

## Problem it solves

Practices that process payments through PayTheory otherwise have to bounce staff out to a separate terminal or portal to take a card, then reconcile that payment back against the Canvas ledger by hand. This plugin puts the card form directly in Canvas's Collect Payment flow: the charge is created in PayTheory and recorded in Canvas in one step, and saved cards mean returning patients don't re-enter their card every visit.

## Who it's for

| Role | Primary use |
|---|---|
| Front-desk / billing staff | Collect a copay or balance payment by card during check-in or checkout |
| Practice manager | Use PayTheory as the card processor of record instead of a standalone terminal |
| Patients | Pay by card with a saved card-on-file for future visits |

**Specialty:** not specialty-specific. Any ambulatory practice on Canvas that uses PayTheory as its card processor can use it.

## How to install

1. Set the required secrets (see **Configuration options** below) for the plugin in your Canvas instance.
2. From this plugin directory, install into a Canvas instance:
   ```bash
   canvas install paytheory_payment_processor --host <your-instance>
   ```
3. Open a patient and start **Collect Payment** → **Credit Card**. The PayTheory card form renders in the modal.

## Configuration options

All configuration is via plugin **secrets** — there are no manifest settings to edit.

| Secret | Required | Description |
|---|---|---|
| `paytheory_merchant_id` | Yes | The merchant's PayTheory UID (used as `merchant_uid` and in the API auth header) |
| `paytheory_public_key` | Yes | The merchant's public SDK key, used to initialize the browser SDK |
| `paytheory_secret_key` | Yes | API secret key for backend GraphQL calls |
| `paytheory_partner` | Yes | Partner prefix for URL construction. Canvas merchants are provisioned under `canvas` |
| `paytheory_environment` | Yes | One of `production`, `sandbox`, or `lab` |

The SDK and API URLs are derived from `paytheory_partner` + `paytheory_environment`:

| Environment | SDK URL | API URL |
|---|---|---|
| production | `{partner}.sdk.paytheory.com` | `api.{partner}.paytheory.com` |
| sandbox | `{partner}.sdk.paytheorystudy.com` | `api.{partner}.paytheorystudy.com` |
| lab | `{partner}.sdk.paytheorylab.com` | `api.{partner}.paytheorylab.com` |

## How it works

1. **Payment form** — Canvas's Collect Payment modal renders the plugin's form, which loads PayTheory's JS SDK and mounts PCI-compliant hosted card fields.
2. **Tokenization** — The card is tokenized client-side into a `payment_method_id`. Live field-validation messages stay inline; only terminal errors (e.g. an issuer decline) surface to the Canvas shell.
3. **Charge** — The token + amount are sent to the backend, which calls PayTheory's `createTransaction` GraphQL mutation (`Authorization: <merchant_id>;<api_key>`). `PENDING`, `SUCCESS`, `SUCCEEDED`, and `SETTLED` are treated as a successful charge; anything else carries `failure_reasons`.
4. **Saved cards** — Patients are mapped to PayTheory payors via `metadata.canvas_patient_id`. Cards can be saved, listed, and disabled per patient.

## Testing

In the **sandbox** environment, charge these dollar amounts to trigger specific outcomes:

| Amount | Result |
|---|---|
| $1.02 | GENERIC_DECLINE |
| $1.93 | INSUFFICIENT_FUNDS |
| $1.94 | INVALID_ACCOUNT_NUMBER |
| $8,899.86 | ADDRESS_VERIFICATION_FAILED_RISK_RULES |
| $8,899.87 | CVV_FAILED_RISK_RULES |
| $8,888.88 | DISPUTE |

Run the unit tests from this directory:

```bash
pytest
```

## Known limitation: transaction status updates

PayTheory transactions initially return `PENDING` (treated as success) and can later transition to `SUCCEEDED`, `FAILED`, `VOIDED`, `SETTLED`, `REFUNDED`, or `DISPUTED`. PayTheory can push these via [webhooks](https://docs.paytheory.com/docs/api/webhooks), but there is currently no Canvas SDK effect to retroactively update a recorded payment's status. Once such an effect exists, a `SimpleAPIRoute` could receive PayTheory webhooks and reconcile late status changes (settlement, refunds, disputes).
