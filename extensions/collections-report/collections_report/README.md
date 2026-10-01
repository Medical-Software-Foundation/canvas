# Collections Report

## What it does

Adds a **Collections** menu item to the provider sidebar that opens a full-page daily collections report. The report shows all payments collected within a date range, broken down by payment method (card, cash, check, other) and patient. A summary bar displays totals by method at the top.

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

## Screenshots

*Coming soon*
