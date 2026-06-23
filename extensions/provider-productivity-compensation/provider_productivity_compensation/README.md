Productivity & Compensation Dashboard
=====================================

## Description

A Canvas plugin that gives providers a real-time view of their daily clinical productivity **and estimated compensation**. The dashboard displays key metrics — patients seen, CPT codes captured, and note signing status — alongside estimated earnings, with configurable time periods and drill-down detail views. Any user can view productivity metrics for any active provider, while estimated compensation stays private to each provider.

## Features

- **Summary metrics cards** showing encounters, total charges, open notes, and estimated compensation (when compensation rates are configured)
- **Time period filtering** — Today, This Week, This Month, This Pay Period, Last Pay Period, or Custom date range
- **Patient encounter list** — collapsible table showing all billable encounters (signed and open) with patient name, date of service, charges, note status badge, estimated compensation, and a patient-name link that opens that encounter's note (via a Canvas permalink) in a new browser tab
- **Charges drill-down** — click a CPT code to see codes grouped by description with counts and earnings, expandable to show each associated patient
- **Estimated compensation** — per-CPT and per-encounter earnings (visible only when viewing your own data, or to designated compensation reviewers)
- **Provider selector** — any user can switch between active providers' metrics via a dropdown to view another provider's encounters and charges

## How It Works

The plugin registers two components:

| Component | Type | Purpose |
|-----------|------|---------|
| `ProductivityDashboardApplication` | Application (global scope) | Opens the dashboard from the application menu |
| `ProductivityDashboardApi` | Protocol (SimpleAPI) | Serves four REST endpoints that return metrics data as JSON |

### API Endpoints

All endpoints are session-authenticated and served under `/plugin-io/api/provider_productivity_compensation`.

| Endpoint | Description |
|----------|-------------|
| `GET /api/providers` | Returns the list of active providers (available to all users) |
| `GET /api/metrics?period=...` | Returns summary counts: encounters, CPT total with earnings, signed/open notes, estimated compensation |
| `GET /api/patients?period=...` | Returns note-level detail rows with patient info, charges, status, and per-encounter earnings |
| `GET /api/cpt-patients?period=...&cpt=CODE` | Returns patients associated with a specific CPT code with per-occurrence earnings |

Period values: `day`, `week`, `month`, `this_pay_period`, `last_pay_period`, `custom` (with `start_date` and `end_date` params).

All endpoints accept a `tz` query parameter (IANA timezone name, e.g. `America/New_York`) so that date range filters use the user's local timezone. The frontend sends this automatically. Dates of service are returned as ISO 8601 timestamps and formatted in the user's browser timezone with a timezone abbreviation (e.g. "EDT", "PDT").

### Metrics Logic

- **Encounters** — total billable notes in the selected period (only notes whose note type has `is_billable=True` are included)
- **Charges** — count of active billing line items with CPT codes on qualifying notes
- **Signed Notes** — notes whose current state is LOCKED, RELOCKED, or SGN (the actual database value for signed notes)
- **Open Notes** — notes whose current state is NEW, PUSHED, CONVERTED, UNLOCKED, RESTORED, or UNDELETED
- **Deleted notes are excluded** — all queries filter through `CurrentNoteStateEvent` with a whitelist of visible states (signed + open), so deleted notes never appear in any metric or list

## Access Control

- All users can open the dashboard and view **any** active provider's encounters and metrics via the provider dropdown.
- **Estimated compensation is private:** a user only sees compensation for their own data.
- **Designated compensation reviewers** may additionally see compensation for any provider they view.
- Estimated compensation is shown only when compensation rates are configured for the provider; otherwise the dashboard renders productivity metrics alone.

## Testing

### Running Tests

```bash
cd provider-productivity-compensation
uv run pytest tests/ -v
```

To check coverage:

```bash
uv run pytest tests/ -v --cov=provider_productivity_compensation --cov-report=term-missing
```

### Manual Checklist

- [ ] Open the "Productivity & Compensation" application from the Canvas application menu
- [ ] Verify the dashboard loads with summary cards (Encounters, Charges, Open Notes, and Estimated Compensation when rates are configured)
- [ ] Toggle between Today / This Week / This Month / Pay Periods / Custom — confirm metrics update
- [ ] Verify the encounters list loads automatically showing patient names, dates, charges, status badges, and note links
- [ ] Click the collapsible divider to collapse/expand the encounters list
- [ ] Click a CPT code in the Charges table — verify it expands to show individual patients
- [ ] Click a patient name link — confirm it opens the correct encounter's note in a new tab
- [ ] Confirm the provider dropdown appears for every user and lists individual active providers
- [ ] Select another provider — confirm their encounters/metrics load but no compensation columns or card are shown
- [ ] As a designated compensation reviewer, confirm compensation is shown when viewing another provider
- [ ] Verify that only billable note types appear in all counts and lists
- [ ] Verify that deleted notes do not appear in any metric or patient list
- [ ] Test with a provider who has no encounters for the selected period — confirm the zero-state renders cleanly

## CANVAS_MANIFEST

The CANVAS_MANIFEST.json is used when installing the plugin. Please ensure it gets updated if you add, remove, or rename files or class names.

Required CANVAS_MANIFEST.json fields:
- sdk_version (string) - The version of the Canvas SDK
- plugin_version (string) - The version of the plugin
- name (string) - The name of the plugin
- description (string) - Description of the plugin
- components (object) - Must have at least 1 component property
- tags (object) - Tags for categorizing the plugin (can be empty: {})
- license (string) - License information (can be empty: "")
- readme (string or boolean) - Path to readme or false
