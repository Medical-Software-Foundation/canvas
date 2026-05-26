# Pre-Visit Brief

A global provider companion app that surfaces a concise pre-visit snapshot for the logged-in provider's next 1–3 appointments today.

## What It Does

When a provider opens the Pre-Visit Brief from the companion launcher, a modal opens showing stacked prep cards — one per upcoming appointment (up to 3), ordered by start time. Each card contains:

- **Patient name** (links to the patient chart, opens in the full Canvas window)
- **Appointment time and type**
- **Last visit** — date and HPI / reason-for-visit snippet from the most recent encounter note
- **Active problems** — conditions marked as `active` and not entered in error
- **Allergies** — active allergy intolerances not entered in error
- **Medications** — active medications not entered in error
- **Vitals** — the most recent vital-sign observations not entered in error

If a section has no data it renders a muted "None on record" rather than hiding the section.

Cancelled and no-show appointments are excluded. If no appointments remain today, the modal shows "No upcoming appointments today."

## Architecture

| Component | Class | Role |
|---|---|---|
| Application | `PreVisitBriefApp` | Opens the modal from the companion launcher |
| SimpleAPI | `BriefAPI` | Serves the HTML shell, static assets, and JSON data |

The browser computes the local-timezone day window (start-of-day to end-of-day as ISO-8601 strings) and passes them as `?start=...&end=...` query parameters to the `/data` endpoint. The server filters appointments within that window, so the brief is always relative to the provider's local clock.

All clinical data (conditions, allergies, medications, observations, notes) is fetched in a single bulk query per model (`patient_id__in`) to avoid N+1 queries.

## Installation

1. Install the plugin in your Canvas instance via the Plugin admin.
2. No secrets are required.
3. The app appears in the companion launcher bar under "Pre-Visit Brief".

## Refreshing Data

Close and reopen the modal. Each open triggers a fresh data fetch with the current day window.
