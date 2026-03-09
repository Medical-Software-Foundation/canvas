# Auto-Submit Clean Claims

## Description

Automatically moves claims from the **Coding** queue to the **Submission** queue when they have no scrub errors.

## How it works

This plugin has two handlers:

1. **SweepCodingQueue** (cron) — Runs every 5 hours and processes all claims currently in the `NeedsCodingReview` queue. This is the primary mechanism and catches newly created claims once they are fully populated with line items, diagnoses, and coverages.

2. **AutoSubmitCleanClaims** (event) — Listens for `CLAIM_CREATED` and `CLAIM_UPDATED` events and re-checks claims in the `NeedsCodingReview` queue. This provides faster feedback when a claim is created or edited (e.g. a missing field is corrected).

Both handlers run the same set of validation checks that mirror Canvas's built-in claim scrubber. If all checks pass (no errors), the claim is automatically moved to `QueuedForSubmission`.

Claims with errors remain in the Coding queue and are labeled with the specific error descriptions. On subsequent runs, labels from previous errors that no longer apply are automatically removed. Labels not owned by this plugin are never touched. Errors are also logged for visibility.

## Video Demonstration

https://www.loom.com/share/bdf680a2889b41baaa959436d67666d8

## Scrub checks performed

### SDK-based checks

| Check | What it validates |
|-------|-------------------|
| Billing Provider Tax ID | Exists and is 9 characters |
| Rendering Provider Tax ID | Exists and is 9 characters |
| Billing Provider NPI | Exists and is 10 characters |
| Rendering Provider NPI | Exists and is 10 characters |
| Hospital dates | POS 21 charges have admit/discharge dates |
| Patient address | Address, city, state, zip all present |
| Patient DOB | Not missing |
| Workers Comp/Auto SSN | SSN present for WC/auto claims |
| Coverage policy ID | Subscriber number present |
| Subscriber address | Present for non-self subscribers |
| Coverage active | Coverage date range includes DOS and stack is IN_USE |
| Service charges | At least one active line item |
| Charge amount | Total billed > $0 |
| Line item units | All charges have units >= 1 |
| NDC codes | Dosage and measure present when NDC code set |
| Diagnosis codes | At least one present |
| Diagnosis pointers | Each charge linked to a diagnosis |
| Duplicate diagnoses | No duplicate codes |
| External cause code | Primary diagnosis not an external cause code |

### FHIR-based checks

| Check | What it validates |
|-------|-------------------|
| CLIA number | Lab charges (proc codes starting with `8`) with QW modifier require a CLIA number |

The CLIA check uses the FHIR API to read the `Claim` resource, since line item modifiers are not exposed in the SDK data models.

## Required secrets

This plugin requires two secrets for the FHIR API (used by the CLIA modifier check):

- **`CANVAS_FHIR_CLIENT_ID`** — OAuth client ID for the FHIR API
- **`CANVAS_FHIR_CLIENT_SECRET`** — OAuth client secret for the FHIR API

Tokens are obtained via the client credentials flow and cached automatically.

## Checks NOT covered

- **NCCI/MUE edits** — requires internal ontologies service (not accessible from plugins)
