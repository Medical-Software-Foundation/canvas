provider-availability
=====================

## What it does

Provider availability engine for Canvas with rule-based scheduling, real-time slot calculation, and an admin configuration UI. It manages open appointment slots across providers, locations, and visit types - including one-off blocks, recurring blocks with same-day/next-day hold types, appointment buffers, and timezone-aware calendar sync. Availability, blocks, and holds can be configured one at a time in the admin UI or bulk-loaded for many staff at once from a CSV.

## Problem it solves

Defining when each provider is bookable - and keeping the Canvas calendar in sync as schedules change - is tedious to do by hand, especially across multiple locations, visit types, and many providers. Practices also need to block time (PTO, holidays, admin time) and reserve same-day or next-day slots without hand-editing calendars. This plugin centralizes all of that: a single admin panel to manage rules/blocks/holds, automatic Clinic/Administrative calendar sync, and a CSV bulk import to stand up or update an entire practice's schedule in one action.

## Who it's for

- **Practice administrators and schedulers** who manage provider open hours, blocked time, and same/next-day holds across locations and visit types.
- **Implementation teams** standing up a new Canvas instance who need to load many providers' (and non-provider staff's) schedules quickly via CSV rather than one rule at a time.

## How to install

Install the plugin with the Canvas CLI, targeting your instance:

```bash
uv run canvas install provider_availability --host <your-host>
```

The core admin UI and calculation engine work with no secrets. To enable the API-key-authenticated provisioning endpoints and restrict who can edit availability, set the secrets below under **Settings > Plugins > provider_availability** in your Canvas instance (see [Configuration options](#configuration-options)).

After install, open **Provider Availability** from the provider menu to manage schedules, or use the **Bulk Import** tab to upload a CSV (see [Bulk CSV import](#bulk-csv-import)).

## Configuration options

### Secrets

| Secret | Purpose |
|--------|---------|
| `simpleapi-api-key` | API key for ProvisionAPI authentication |
| `allowed-staff-keys` | Comma-separated staff key UUIDs allowed to edit rules in the admin UI (and to commit a bulk import). Empty = allow all staff (bootstrap). |

### Practice and provider timezones

Set a practice-level default timezone in the admin UI **Settings** tab, with optional per-provider overrides. All times are stored in UTC internally; changing a provider's timezone re-syncs all of their calendar events.

## Screenshots

**Availability overview** - at-a-glance view of every provider's rules, blocks, and holds:

![Availability overview](../screenshots/01-availability-overview.png)

**Recurring availability rule** - flexible recurrence with `Every N Week(s) / Day(s)` (bi-weekly, every 17 days, etc.):

![Recurring availability rule](../screenshots/02-recurring-rule.png)

**Multi-date holiday batch** - All-day toggle plus a chip picker to queue several dates and save them in one action:

![Multi-date holiday batch](../screenshots/03-holiday-batch.png)

## Features

- **Admin UI**: Configure availability rules, blocks, and recurring blocks via an in-app panel (provider menu item), with Availability / Add-Edit / Settings / Bulk Import tabs.
- **CSV Bulk Import**: Upload a CSV to load availability rules, one-off blocks, and recurring blocks for one or many staff at once, with per-row validation, overlap detection, and a preview before commit (see [Bulk CSV import](#bulk-csv-import)).
- **REST API**: Query available slots, list providers, and manage rules/blocks programmatically.
- **Calculation Engine**: Computes bookable time slots from weekly schedules, booking constraints, buffer times, and existing appointment conflicts.
- **Calendar Sync**: Syncs rules and blocks to Canvas Calendar Events (Clinic = available, Administrative = blocked).
- **Hold Types**: Recurring blocks with same-day or next-day hold release on a rolling 30-day window.
- **Appointment Buffers**: Automatic pre/post buffer events on Administrative calendars when appointments are created/rescheduled/canceled.
- **Timezone Support**: Practice-level default with per-provider overrides; all times stored UTC internally.
- **Cache-backed Storage**: Rules stored in plugin cache with TTL refresh.

## Bulk CSV import

Open the **Provider Availability** admin (provider menu) and select the **Bulk Import** tab to bulk-load availability from a spreadsheet. The flow is upload -> validate/preview -> commit. Download the template from the tab (or `GET /csv/template`).

### How rows become records

Availability is nested (a rule has a weekly schedule of multiple day/time windows), so the CSV is flat: **one row per time window**. Rows are grouped into records server-side. Rows that share the same staff member and rule-level settings (location, visit type, buffer, booking, recurrence, effective dates) merge into a single rule whose weekly schedule accumulates each row's window. Set an explicit `group_key` to force rows to merge.

Example: staff member X, Main Clinic, Monday 9-12 and 1-5 = two `rule` rows that merge into one rule with two Monday windows.

Rows are keyed by `staff_key` (the Canvas Staff UUID), not NPI - so availability can be loaded for providers, non-provider staff, and any schedulable staff record. The staff key is the same identifier used by the `allowed-staff-keys` secret.

### Row types (`type` column)

| Type | Meaning | Key columns |
|---|---|---|
| `rule` | A bookable availability window | `day`, `start`, `end`, `location`, `visit_type`, buffer/booking columns |
| `block` | A one-off unavailable date or range | `date`, `all_day`, `start`, `end`, `reason` |
| `rblock` | A recurring unavailable window (incl. holds) | `day`, `start`, `end`, `reason`, `hold_type` |

### Columns

| Column | Applies to | Notes |
|---|---|---|
| `type` | all | `rule`, `block`, or `rblock` |
| `staff_key` | all | Canvas Staff UUID. Validated against active staff. Works for providers and non-provider staff. |
| `location` | rule, block, rblock | Location name (not ID). Blank = all locations. `\|`-separate for multiple. |
| `visit_type` | rule | Visit-type name. Blank = all types. `\|`-separate for multiple. |
| `day` | rule, rblock (weekly) | `monday`..`sunday`. Ignored when `recurrence_frequency=daily`. |
| `start`, `end` | rule, rblock, timed block | `HH:MM` 24-hour; `start` must be before `end` |
| `all_day` | block | `true`/`false`. When true, `start`/`end` are ignored. |
| `date` | block | `YYYY-MM-DD` |
| `reason` | block, rblock | Free text |
| `hold_type` | rblock | `none`, `same_day`, or `next_day` (default `none`) |
| `buffer_pre`, `buffer_post` | rule | Minutes (default 0 / 15) |
| `min_lead_hours`, `slot_minutes` | rule | Default 24 / 15 |
| `recurrence_frequency` | rule, rblock | `weekly` (default) or `daily` |
| `recurrence_interval` | rule, rblock | Integer >= 1 (default 1) |
| `effective_start`, `effective_end` | rule, rblock | `YYYY-MM-DD`, optional |
| `group_key` | rule, rblock | Optional; forces rows to merge into one record |

### Validation

Each row is validated for format and required fields, then the staff key is checked against active staff and location/visit-type names are resolved to Canvas IDs (unknown staff keys or unresolved location/visit-type names become row errors). New rules are checked against existing saved rules for overlap; overlapping windows within one group are also flagged. Only clean records are committed. Cross-record overlaps within the same upload for the same provider are evaluated against saved rules once committed.

## Architecture

| Component | Handler Type | Description |
|-----------|-------------|-------------|
| `ProviderAvailabilityApp` | Application | Provider menu item that opens the admin UI (includes the Bulk Import tab) |
| `AvailabilityAPI` | SimpleAPI | REST endpoints for availability queries, rule/block CRUD, and admin UI/asset serving |
| `CSVImportAPI` | SimpleAPI | Staff-session endpoints for the CSV bulk import (validate / commit / template) |
| `ProvisionAPI` | SimpleAPI | API key-authenticated provisioning and practice-timezone management |
| `CacheRefreshTask` | CronTask | TTL refresh, lead-time block generation, hold block rolling window (every 5 min) |
| `OnStaffActivated` | Protocol | Creates Clinic calendar when a provider is activated |
| `OnStaffDeactivated` | Protocol | Cleans up rules and calendar events when a provider is deactivated |
| `OnPluginInstalled` | Protocol | Full sync of all cached rules/blocks to Calendar Events on install and redeploy |
| `OnAppointmentCreated` | Protocol | Creates buffer events on Administrative calendar |
| `OnAppointmentRescheduled` | Protocol | Updates buffer events when appointment is rescheduled |
| `OnAppointmentCanceled` | Protocol | Removes buffer events when appointment is canceled |

## API Endpoints

### AvailabilityAPI (session-authenticated)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/available-slots` | Query available slots for a provider and date range |
| GET | `/available-providers` | Find providers with availability for a date/visit type |
| GET | `/providers/list` | List all active providers |
| GET | `/providers/search` | Search providers by name/ID |
| GET | `/locations` | List all active locations |
| GET | `/visit-types` | List all scheduleable visit types |
| GET | `/overview` | Aggregate overview of all providers with rules/blocks |
| GET | `/rules` | List all rules |
| GET | `/rules/<provider_id>` | Get rules for a specific provider |
| POST | `/rules` | Create an availability rule |
| PUT | `/rules` | Update an availability rule |
| DELETE | `/rules/<provider_id>/<rule_id>` | Delete a single rule |
| DELETE | `/rules/<provider_id>` | Delete all rules for a provider |
| GET | `/blocks/<provider_id>` | Get one-off blocks for a provider |
| POST | `/blocks` | Create a one-off block |
| PUT | `/blocks` | Update a one-off block |
| DELETE | `/blocks/<provider_id>/<block_id>` | Delete a block |
| GET | `/recurring-blocks/<provider_id>` | Get recurring blocks for a provider |
| POST | `/recurring-blocks` | Create a recurring block |
| PUT | `/recurring-blocks` | Update a recurring block |
| DELETE | `/recurring-blocks/<provider_id>/<block_id>` | Delete a recurring block |
| GET | `/timezone` | Get practice timezone and available options |
| PUT | `/timezone` | Set practice timezone (re-syncs all rules/blocks) |
| GET | `/provider-timezone?provider_id=` | Get provider-specific timezone |
| GET | `/provider-timezones/all` | Get all provider timezone overrides |
| PUT | `/provider-timezone` | Set a provider timezone (re-syncs all their rules, blocks, and recurring blocks) |
| PUT | `/provider-timezones/bulk` | Set timezones for multiple providers at once |
| GET | `/availability-admin` | Serve admin UI HTML with preloaded data |
| POST | `/form-action` | CSP-compliant form dispatch for admin UI writes |
| GET | `/admin.css` | Admin UI stylesheet |
| GET | `/admin.js` | Admin UI JavaScript |
| GET | `/tokens.css`, `/typography.css`, `/canvas-components.js` | Canvas design-system static assets |

### CSVImportAPI (session-authenticated)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/csv/template` | Download the CSV template |
| POST | `/csv/validate` | Upload a CSV (multipart `file`), returns per-row errors and previewed records |
| POST | `/csv/commit` | Persist previewed records and sync calendar events (gated by `allowed-staff-keys`) |

### ProvisionAPI (API key-authenticated)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/provision/run` | Create Clinic calendars and Available events for all active providers |
| GET | `/provision/timezone` | Get practice timezone |
| PUT | `/provision/timezone` | Set practice timezone |

## Data Model

### Secrets

| Secret | Purpose |
|--------|---------|
| `simpleapi-api-key` | API key for ProvisionAPI authentication |
| `allowed-staff-keys` | Comma-separated staff UUIDs allowed to open the admin UI and edit rules. Dashed or undashed UUIDs both work. Leave empty/unset to allow any logged-in Canvas staff member (bootstrap). |

### Data Model

**ProviderAvailabilityRule** — Defines when a provider is available:
- Weekly schedule (time windows per day), location/visit type filters
- Booking interval (min lead hours, slot granularity)
- Buffer times (pre/post appointment minutes)
- Effective date range, group ID for bulk edits

**AdminBlock** - One-off time block when a provider is unavailable:
- Start/end datetime, reason, location filter
- Group ID for bulk edits

**RecurringBlock** - Weekly or daily recurring block with optional hold:
- Weekly schedule, reason, location filter, effective date range
- Hold type: `none` (immediate block), `same_day` (releases day-of), `next_day` (releases day before)

## Calendar Integration

- **Clinic calendars**: Events define when a provider IS available for booking
- **Administrative calendars**: Events define when a provider is NOT available
- Buffer and blocking events are placed on Administrative calendars
- Hold blocks are dynamically created/released on a rolling 30-day window

## Info

*This plugin was developed and contributed by [Vicert](https://vicert.com).*
Contact: engineering@vicert.com
