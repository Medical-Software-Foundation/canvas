# Collections Report

## What it does

Adds a **Collections** menu item to the provider sidebar that opens a full-page financial report with two tabs:

- **Collections**: all payments collected within a date range, broken down by payment method (card, cash, check, other) and patient. A summary bar displays totals by method at the top.
- **Balances Owed**: every patient with an outstanding balance, largest first, with their number of open claims and oldest unpaid date of service. Totals follow the same rule Canvas uses for a patient's balance (trashed claims, claims on an active installment plan, and negative-balance claims with no insurance posting are excluded). Both tabs download as CSV.

## Problem it solves

Practices need a quick, at-a-glance view of payments collected each day for reconciliation and end-of-day reporting. Without this, staff must navigate through individual patient accounts or export data from the revenue module to answer "how much did we collect today?"

## Who it's for

- Front desk and billing staff who reconcile daily payments
- Practice managers who review collections performance
- Providers at cash-pay or self-pay practices who want visibility into daily revenue

## How to install

1. Install the plugin via the Canvas CLI or Studio
2. No secrets or configuration required — the plugin works out of the box
3. The **Collections** menu item will appear in the provider sidebar under the bottom section

## Configuration options

No configuration is required. The plugin uses read-only access to the following Canvas SDK data models:

- `PaymentCollection` — payment records with method, amount, and description
- `BulkPatientPosting` — links payments to patients
- `BasePosting` — posting details
- `Claim` — claim references
- `Patient` — patient name display
- `Note` — date of service for the oldest open claim
- `InstallmentPlan`, `ClaimCoverage`, `CoveragePosting` — to apply Canvas's patient balance rules

## Screenshots

*Coming soon*
