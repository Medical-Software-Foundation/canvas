# Candid Health Integration — User Guide

## Overview

The Candid Health plugin connects your Canvas EHR to Candid Health's billing platform. It handles the complete claim lifecycle automatically:

1. **Claim submission** — When you queue a claim for submission, it's sent to Candid
2. **Adjudication sync** — Insurance payment data (ERAs) is pulled from Candid and posted to your claims
3. **Patient payment reporting** — When you collect a patient payment in Canvas, it's reported to Candid
4. **Patient payment sync** — Payments recorded in Candid are pulled back into Canvas

## What Happens Automatically

### When you move a claim to the Submission queue

The plugin waits **60 seconds** before submitting — this gives you time to undo an accidental queue move. If you move the claim out of the submission queue within that window, no submission happens.

After the grace period:
- **On success:** The claim moves to **Filed Awaiting Response**, a comment is added ("Claim submitted to Candid on..."), and a blue status banner appears
- **On failure:** The claim moves to **Needs Coding Review** with an error comment explaining what went wrong, and a warning banner appears

For claims with more than 12 diagnosis codes, the plugin automatically splits into multiple Candid encounters (primary + supplemental) to stay within CMS-1500 limits. You'll see a comment like "Claim submitted to Candid on 2026-05-01 across 2 encounters."

### When adjudication data arrives from Candid

A nightly sync runs at **2:00 AM** to check all claims in Filed Awaiting Response, Adjudicated Open Balance, and Patient Balance queues. When new ERA (Electronic Remittance Advice) data is found:

- Insurance payments are posted to the claim (charged, allowed, paid amounts per service line)
- Payer adjustments are posted with their CARC codes (e.g. CO-45, PR-1)
- If the remaining balance is the patient's responsibility, the balance transfers to the patient
- The claim moves to **Patient Balance** or **Adjudicated Open Balance** depending on the remaining balances
- The status banner updates (e.g. "Candid: Era Received | Last synced 2026-05-01")

Denied claims show a **warning banner** (e.g. "Candid: Denied | Last synced 2026-05-01").

### When you collect a patient payment

When you post a patient payment on a claim, it's automatically reported to Candid with the correct allocation to the Candid encounter. If the report fails, a **Task** is created in Canvas labeled "Candid Integration" so you know to follow up.

### When a patient payment is recorded in Candid

When the sync finds patient payments in Candid that haven't been recorded in Canvas, it posts them to the claim automatically. These show up as patient postings with a description like "Candid patient payment pay-abc123."

## Candid Activity Panel

When you're viewing a claim, open the **Candid Activity** app from the app drawer (look for the Candid icon). It opens a panel on the right side showing:

### Status Bar

At the top, you'll see the current Candid status:
- **Blue** — Normal status (e.g. "Candid: Era Received | Submitted 2026-04-24 | Last synced 2026-05-01")
- **Yellow** — Warning (e.g. "Candid: Denied | ..." or "Candid: Submission failed 2026-05-01")
- **Grey** — "Not yet submitted to Candid"

### Activity Timeline

A chronological list of all Candid-related activity on the claim, newest first:

| Event | Color | What it shows |
|-------|-------|--------------|
| **ERA Synced** | Green | ERA ID and total paid amount (e.g. "era-test-1 ($70.00)") |
| **Sync** | Yellow | Sync result — effects count, Candid status, ERA IDs processed |
| **Patient Payment Reported** | Purple | Amount and Candid payment ID for outbound payments |
| **Patient Payment Synced** | Purple | Inbound payments pulled from Candid |
| **Submitted to Candid** | Blue | Submission date, encounter count, encounter IDs |
| **Submission Failed** | Red | Error message from Candid |
| **Claim Comment** | Grey | Candid-related comments on the claim |

### Summary

At the bottom, pill badges show totals:
- **Green pill** — Total number of ERAs synced
- **Purple pill** — Total number of patient payments (inbound + outbound)

### Sync Now Button

Click **Sync Now** to trigger an immediate full adjudication sync for this claim. This is useful when:
- You want to check for new ERA data without waiting for the nightly cron
- You've just resolved an issue and want to re-sync
- You want to verify the current Candid status

The timeline refreshes automatically after syncing.

## Candid Claims Dashboard

The **Candid Dashboard** is a full-page application accessible from the Canvas provider menu. It gives you an overview of all claims that have been submitted to Candid.

### What You See

A sortable, filterable table of all Candid-submitted claims showing:

| Column | What it shows |
|--------|--------------|
| **Patient** | Patient name — click any row to navigate directly to that claim |
| **Candid Status** | Current status from Candid, shown as a color-coded pill |
| **Canvas Queue** | Which Canvas queue the claim is currently in |
| **Submitted** | Date the claim was submitted to Candid |
| **Last Sync** | Date of the most recent adjudication sync |

### Status Pills

| Color | Meaning | Examples |
|-------|---------|---------|
| **Green** | Paid | `finalized paid`, `paid` |
| **Blue** | In progress | `era received`, `biller received`, `coded` |
| **Yellow** | Denied | `denied`, `finalized denied` |
| **Red** | Error | Submission failed — click to see the error |
| **Grey** | Pending | Submitted but no adjudication data yet |

Rows with errors have a red background; denied claims have a yellow background for quick visual scanning.

### Filtering

- **Errors / denials only** — Checkbox to show only claims that need attention
- **Candid Status** — Click the column header filter to select specific statuses (e.g. show only "denied" and "era received")
- **Canvas Queue** — Filter to specific queues (e.g. show only claims in "Patient Balance")
- **Patient search** — Click the search filter on the Patient column to search by patient name

Filters can be combined. The summary in the filter bar shows how many claims match (e.g. "12 of 156 claims").

### Sorting

Use the "Sorted by" dropdown to change the sort order:
- **Most recent activity** (default) — Claims with the newest sync or submission first
- **Submitted** — By submission date
- **Last sync** — By most recent sync date
- **Candid status** — Alphabetical by status
- **Canvas queue** — Alphabetical by queue name

Toggle ascending/descending with the direction dropdown.

### Actions

- **Refresh** — Click to reload the dashboard data
- **Click any row** — Navigate directly to that claim's detail page

## Claim Queues

The plugin moves claims between queues based on what it learns from Candid:

| Trigger | Destination Queue |
|---------|------------------|
| Successful submission | Filed Awaiting Response |
| Failed submission | Needs Coding Review |
| ERA received, insurance balance remaining | Adjudicated Open Balance |
| ERA received, only patient balance remaining | Patient Balance |
| ERA received, no balance remaining | Adjudicated Open Balance |

## Claim Banners

Every claim processed through Candid shows a status banner at the top of the claim page:

| State | Banner | Style |
|-------|--------|-------|
| Submitted | "Candid: Submitted 2026-04-24 \| Awaiting response" | Info (blue) |
| Submitted (split) | "Candid: Submitted 2026-04-24 (2 encounters) \| Awaiting response" | Info (blue) |
| Synced | "Candid: Era Received \| Submitted 2026-04-24 \| Last synced 2026-05-01" | Info (blue) |
| Denied | "Candid: Denied \| Submitted 2026-04-24 \| Last synced 2026-05-01" | Warning (yellow) |
| Failed | "Candid: Submission failed 2026-05-01" | Warning (yellow) |

## Duplicate Prevention

The plugin tracks what's already been synced to prevent double-posting:

- **ERA data**: Each ERA has a unique ID. Once posted, the ID is recorded so it's never posted again — even if the sync runs multiple times.
- **Patient payments (outbound)**: When Canvas reports a payment to Candid, the returned payment ID is stored so the inbound sync knows not to re-post it.
- **Patient payments (inbound)**: When Candid payments are synced to Canvas, their IDs are stored so they're not posted again on the next sync.

## Configuration

The plugin requires three secrets to be configured per instance:

| Secret | Description |
|--------|-------------|
| `CANDID_CLIENT_ID` | Your Candid Health OAuth2 client ID |
| `CANDID_CLIENT_SECRET` | Your Candid Health OAuth2 client secret |
| `CANDID_BASE_URL` | Candid API URL — `https://api.joincandidhealth.com` for production, `https://api-staging.joincandidhealth.com` for staging |

No other configuration is needed. The plugin automatically detects the Canvas instance URL and uses the Candid credentials for internal authentication.

## Troubleshooting

**Claim stuck in "Filed Awaiting Response" with no adjudication data:**
Open the Candid Activity panel and click "Sync Now." Check the timeline for any sync errors.

**Submission failed:**
Check the claim's activity log for the error comment (e.g. "Candid: claim has validation errors: ..."). Fix the issue (usually missing patient or provider data) and move the claim back to the Submission queue.

**Patient payment not reported to Candid:**
Look for a Task labeled "Candid Integration" — it will contain the error details. Common causes: Candid API temporarily unavailable, or the payment context was missing claim allocation data.

**Duplicate postings:**
This shouldn't happen — the plugin tracks all synced IDs. If it does, check the claim metadata for `candid_synced_adjudication_ids` and `candid_synced_payment_ids` to see what's been recorded.

**Plugin not handling submissions (built-in is running instead):**
Verify the plugin is enabled in Canvas admin. When enabled, the built-in Candid integration automatically stands down.

**Need to disable the plugin:**
Disable it in Canvas admin. The built-in integration resumes immediately — no code deploy needed.
